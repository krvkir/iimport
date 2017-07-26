import os
import sys
import types
from functools import reduce

import importlib
import re
import logging

import nbformat
from IPython import get_ipython
from IPython.core.inputtransformer import InputTransformer, CoroutineInputTransformer
from IPython.core.interactiveshell import InteractiveShell
from IPython.core.magic import register_line_magic

#
# Procedure collector
#

_tag_re = '^(?P<indent> *)%(?P<tagcode>[a-zA-Z+\-\\/<>*]+) *'
tags = {
    '@': 'DECORATOR',
    'def': 'BEGIN_PROC',
    'return': 'END_PROC',

    '-': 'SKIP_LINE',
    '//': 'SKIP_LINE',
    '--': 'TOGGLE_SKIP',

    '/*': 'BEGIN_SKIP',
    '*/': 'END_SKIP',

    '+': 'INSERT_LINE',
    '++': 'TOGGLE_INSERT',
}
_procname_re = '(?P<name>[a-zA-Z0-9_]+)'\
               ' *\((?P<params>[a-zA-Z0-9.\[\],_= \'\"]*)\)'\
               ' *\:'

class Procedure(object):
    @staticmethod
    def name_from_value(value):
        name = re.sub('[\'\"\[\]\.]+', '_', value)
        name = re.sub('_+$', '', name)
        return name

    @staticmethod
    def parse_param(param):
        """
        Three cases are supported:
        1. one value looking like parameter name
        2. one value looking like parameter default value (like array or dict item, object property or simply a string)
        3. two values: parameter name and default value

        In case 2 we generate dummy variable name from its value (args.path -> args_path, args['path'] -> args__path__).

        Later in we'll substitute all entries of variable default value in function's body by the name
        of corresponding variable.
        """
        items = [s.strip() for s in param.split('=')]
        if len(items) == 1:
            default = items[0]
            name = Procedure.name_from_value(default)
            if name == default:
                default = None
        elif len(items) == 2:
            name, default = items
        else:
            raise Exception(f"Cannot process parameter definition: {param}")
        return name, default

    def __repr__(self):
        return self.__dict__.__repr__()

    def __init__(self, m_name, meta):
        self.name = m_name.group('name')

        self.params = [self.parse_param(param) for param in m_name.group('params').split(',')]
        self.param_names = [k for k, v in self.params]
        self.param_defaults = [v for k, v in self.params]
        self.param_substs = [(v, k) for k, v in self.params if v is not None]

        self.body = []

        self.indent = meta['indent']
        logging.debug("Procedure metadata from header:\n%s" % self)

    def add_line(self, line, meta):
        assert line.startswith(self.indent)
        # Trim indentation
        line = line[len(self.indent):]
        # Substitute parameter values by its names
        line = reduce(lambda s, r: s.replace(*r), self.param_substs, line)
        self.body.append(line)

    def end(self, results, meta):
        self.results = [s.strip() for s in results.split(',')]
        self.body.append('return %s' % ', '.join(self.results))

        comment_lines = (
            ['"""']
            + [':param %s' % (f'{k}={v}' if v else k) for k, v in self.params]
            + ["Returns: %s" % ', '.join(self.results)]
            + ['"""']
            )

        text = "\ndef %s(%s):\n" % (self.name, ', '.join(f'{k}={v}' if v else k for k, v in self.params))
        text += '\n'.join('    %s' % s for s in comment_lines + self.body)
        return text

    def call(self, meta):
        params = ', '.join(v if v is not None else k for k, v in self.params)
        results = ', '.join(self.results)
        return f"{self.indent}{results} = {self.name}({params})"


def consumer(func):
    def wrapper(*args, **kwargs):
        g = func(*args, **kwargs)
        next(g)
        return g
    wrapper.__name__ = func.__name__
    wrapper.__dict__ = func.__dict__
    wrapper.__doc__ = func.__doc__
    return wrapper

@consumer
def fetch_tag(destination, opts={}):
    tag_re = re.compile(_tag_re)

    # Things to be pushed to coroutines chain
    # Line following after tag
    line_out = None
    # Dict of metainformation collected
    meta = {}

    while True:
        line = (yield line_out)
        while line is None:
            line = yield

        tag = 'CODE'
        m = tag_re.match(line)
        if m:
            # fetch tag from tagcode
            tagcode = m.group('tagcode')
            if tagcode in tags:
                tag = tags[tagcode]
                line = line[len(m.group(0)):]
                logging.debug("Found tag: %s" % tag)
            # save indent to substract it from procedure lines
            indent = m.group('indent')
            assert len(indent) % 4 == 0
            meta['indent'] = indent

        # If processing is disabled, ignore all tags
        if opts.get('enabled', True):
            line_out = destination.send((tag, line, meta))
        else:
            if tag in ['BEGIN_PROC']:
                line_out = None
            else:
                line_out = line

@consumer
def collect_proc(destination):
    # Stack of procedures in declaration (to support procedures declaration nesting)
    stack = []
    # Procedure data
    proc = None

    procname_re = re.compile(_procname_re)

    # Processing all the input line by line
    tag, line, meta = yield
    while True:
        line_out = None

        if tag == 'BEGIN_SKIP':
            # Skip all from this line to the line where END_SKIP tag will be found
            # (or to the end of the file).
            while tag != 'END_SKIP':
                if tag in ['BEGIN_PROC']:
                    tag, line, meta = yield
                else:
                    tag, line, meta = yield destination.send((None, line, meta))

            tag, line, meta = yield destination.send(('CODE', line, meta))

        if tag == 'SKIP_LINE':
            # Execute line in the notebook but do not add it to the procedure.
            # (Useful for in-notebook plotting or debug output which is of no need
            # in the non-interactive code.)
            line_out = destination.send((tag, line, meta))
        elif tag == 'BEGIN_PROC':
            # Check procedure name for correctness and parse it into name, params and results
            #
            # If procedure declaration started while another procedure already being collected,
            # then push the old one on top of the stack and process the new one. (It will be declared
            # in global namespace to be importable.)
            m_name = procname_re.match(line)
            if m_name:
                stack.append(proc)
                proc = Procedure(m_name, meta)
            else:
                logging.error('Wrong proc name: %s' % line)
        elif tag == 'CODE':
            if proc is not None:
                # Add line to the procedure body.
                proc.add_line(line, meta)
                line_out = destination.send(('PROC_CODE', line, meta))
            else:
                line_out = destination.send(('CODE', line, meta))
        elif tag == 'END_PROC' and proc is not None:
            # Stop collecting the procedure and declare it.
            # It this one is inside another, then add to the outer one the line like this:
            #
            # `result1, ... , result_n = inner_proc(param1, ... , param_m)`
            #
            # which is equivalent transformation if the outer proc uses only declared results
            # of the inner one.
            text = proc.end(line, meta)
            call = proc.call(meta)
            proc = stack.pop()
            if proc is not None:
                proc.add_line(call, meta)
            logging.debug(f'Defining a function:{text}')
            line_out = destination.send((tag, text, meta))
        else:
            logging.error("Wrong state: tag=%s, line=%s" % (tag, line))

        tag, line, meta = (yield line_out)

@consumer
def output_filter(is_module=False):
    """
    is_module:
      False -- treat input as interactive notebook:
        execute all lines, declare all procedures
      True -- treat input as module:
        execute all lines except ones inside procedures and explicitly skipped,
        declare all procedures
    """
    line_out = None
    while True:
        tag, line, meta = (yield line_out)
        line_out = line if not is_module or (tag in ['CODE', 'END_PROC']) else None

#
# .ipynb import mechanism
#

def find_notebook(fullname, path=None):
    name = fullname.rsplit('.', 1)[-1]
    if not path:
        path = ['']
    for d in path:
        nb_path = os.path.join(d, name + '.ipynb')
        if os.path.isfile(nb_path):
            return nb_path
        # try with hyphens
        nb_path_hyp = nb_path.replace('_', '-')
        if os.path.isfile(nb_path_hyp):
            return nb_path_hyp
        # try with spaces
        nb_path_spc = nb_path.replace('_', ' ')
        if os.path.isfile(nb_path_spc):
            return nb_path_spc

class NotebookFinder(object):
    def __init__(self):
        self.loaders = {}

    def find_module(self, fullname, path=None):
        nb_path = find_notebook(fullname, path)
        if not nb_path:
            return

        key = path
        if path:
            key = os.path.sep.join(path)

        if key not in self.loaders:
            self.loaders[key] = NotebookLoader(path)
        return self.loaders[key]

class NotebookLoader(object):
    def __init__(self, path=None):
        self.shell = InteractiveShell.instance()
        self.path = path

        newline_cutter = re.compile('\n\n\n\n*')
        self.output_filters = [
            lambda s: newline_cutter.sub('\n\n\n', s),
            ]

    def load_module(self, fullname):
        path = find_notebook(fullname, self.path)

        logging.info("Importing notebook %s" % path)
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, 4)

        mod = types.ModuleType(fullname)
        mod.__file__ = path
        mod.__loader__ = self
        mod.__dict__['get_ipython'] = get_ipython
        sys.modules[fullname] = mod

        save_user_ns = self.shell.user_ns
        self.shell.user_ns = mod.__dict__

        text = self.process_ipynb(nb)
        try:
            mod.__source__ = source = self.shell.input_transformer_manager.transform_cell(text)
            mod.__numbered_source__ = numbered_source ='\n'.join(['%4i %s' % (n+1, l) for n, l in enumerate(source.split('\n'))])
            exec(source, mod.__dict__)
        except Exception:
            exc_type, exc, tb = sys.exc_info()
            logging.error("Exception during module code execution: line %i, %s" % (tb.tb_lineno, exc))
            logging.error("Executing module source:\n%s" % numbered_source)
            raise e
        finally:
            self.shell.user_ns = save_user_ns
            return mod

    def process_ipynb(self, nb):
        """
        Pass the notebook through procedure collection filter and return parsed text.
        """
        self.chain = fetch_tag(collect_proc(output_filter(is_module=True)))
        lines_out = []

        for cell in nb.cells:
            cell_lines = [l for l in cell.source.split('\n') if l is not None]
            if cell.cell_type != 'code':
                cell_lines = ['#### ' + l for l in cell_lines]
            cell_lines_out = [l for l in (self.chain.send(l) for l in cell_lines) if l is not None]
            if len(cell_lines_out) > 0:
                lines_out += cell_lines_out
                lines_out.append('\n')
        text = '\n'.join(lines_out)

        for f in self.output_filters:
            text = f(text)
        return text



#
# Extension activation function
#

def load_ipython_extension(ip):
    # Registering ipynb import mechanism
    sys.meta_path.append(NotebookFinder())

    # Activating procedure collector
    chain_opts = {'enabled': 0}
    @CoroutineInputTransformer.wrap
    def chain():
        chain = fetch_tag(collect_proc(output_filter()), opts=chain_opts)
        line = yield
        while True:
            line = yield chain.send(line)

    ip.input_splitter.physical_line_transforms.append(chain())
    ip.input_transformer_manager.physical_line_transforms.append(chain())

    # Registering magics
    def iimport_enabled(line):
        """  Magic to toggle iimport mode
        0 = disabled, all macro commands are ignored (cutted away from the code)
        1 = enabled, all macro commands work
        """
        enabled = int(line)
        if enabled == 0:
            chain_opts['enabled'] = 0
            print("iimport macros disabled")
        elif enabled == 1:
            chain_opts['enabled'] = 1
            print("iimport macros enabled")
        else:
            logging.error(f"Wrong argument supplied: {enabled}")

    shell = InteractiveShell.instance()
    def iimport(line):
        path, *args = line.split()
        if len(args) == 0:
            name = reduce(lambda s, c: s.replace(c, '_'), ',. -', path).lower()
        elif len(args) >= 1 and args[0] == 'as':
            name = args[1]
        else:
            raise ImportError()
        shell.user_ns[name] = importlib.import_module(path)

    register_line_magic(iimport_enabled)
    register_line_magic(iimport)

    print('iimport loaded.')

def unload_ipython_extension(ip):
    print("Unloading this extension is currently not implemented, please restart the kernel.")
