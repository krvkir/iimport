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
# JI procedure collector
#

_tag_re = '^(?:    )*%([a-zA-Z+\-\\/<>*]+)[ ]*'
tags = {
    '<': 'BEGIN_PROC',
    '>': 'END_PROC',
    'def': 'BEGIN_PROC',
    'end': 'END_PROC',
    '-': 'SKIP_LINE',
    '//': 'SKIP_LINE',
    '/*': 'BEGIN_SKIP',
    '*/': 'END_SKIP',
}
_procname_re = '([a-zA-Z0-9_]+)'\
               ' *\(([a-zA-Z0-9,_= \'\"]+)\)'\
               ' *-> *([a-zA-Z0-9_, ]+)'

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

    line_out = None
    while True:
        line = (yield line_out)
        while line is None:
            line = yield

        tag = 'CODE'
        m = tag_re.match(line)
        if m:
            tagcode = m.group(1)
            if tagcode in tags:
                tag = tags[tagcode]
                line = line[len(m.group(0)):]
                logging.debug("Found tag: %s" % tag)

        # If processing is disabled, ignore all tags
        if opts.get('enabled', True):
            line_out = destination.send((tag, line))
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
    proc = {}
    proc_name = None
    proc_param_names = None
    proc_param_defaults = None
    proc_results = None
    proc_body = None

    procname_re = re.compile(_procname_re)

    # Processing all the input line by line
    tag, line = yield
    while True:
        line_out = None

        if tag == 'BEGIN_SKIP':
            # Skip all from this line to the line where END_SKIP tag will be found
            # (or to the end of the file).
            while tag != 'END_SKIP':
                if tag in ['BEGIN_PROC']:
                    tag, line = yield
                else:
                    tag, line = yield destination.send((None, line))

        if tag == 'SKIP_LINE':
            # Execute line in the notebook but do not add it to the procedure.
            # (Useful for in-notebook plotting or debug output which is of no need
            # in the non-interactive code.)
            line_out = destination.send((tag, line))
        elif tag == 'BEGIN_PROC':
            # Check procedure name for correctness and parse it into name, params and results
            #
            # If procedure declaration started while another procedure already being collected,
            # then push the old one on top of the stack and process the new one. (It will be declared
            # in global namespace to be importable.)
            m_name = procname_re.match(line)
            if m_name:
                stack.append((proc_name, proc_param_names, proc_param_defaults, proc_results, proc_body))
                proc_name = m_name.group(1)
                param_entries = [[s.strip() for s in S.split('=')] for S in m_name.group(2).split(',')]
                proc_param_names = [kv[0] for kv in param_entries]
                proc_param_defaults = [kv[1] if len(kv) == 2 else None for kv in param_entries]
                proc_results = [s.strip() for s in m_name.group(3).split(',')]
                proc_body =\
                    ['"""', 'Parameters:'] +\
                    [':param %s' % (f'{k}={v}' if v else k) for k, v in zip(proc_param_names, proc_param_defaults)] +\
                    ["", "Returns:"] + ['%s' % s for s in proc_results] + ['"""']
            else:
                logging.error('Wrong proc name: %s' % line)
        elif tag == 'CODE':
            if proc_name is not None:
                # Add line to the procedure body.
                proc_body.append(line)
                line_out = destination.send(('PROC_CODE', line))
            else:
                line_out = destination.send(('CODE', line))
        elif tag == 'END_PROC' and proc_name is not None:
            # Stop collecting the procedure and declare it.
            # It this one is inside another, then add to the outer one the line like this:
            #
            # `result1, ... , result_n = inner_proc(param1, ... , param_m)`
            #
            # which is equivalent transformation if the outer proc uses only declared results
            # of the inner one.
            proc_body.append('return %s' % ', '.join(proc_results))
            text = "\ndef %s(%s):\n" % (
                proc_name,
                ', '.join(f'{k}={v}' if v else k for k, v in zip(proc_param_names, proc_param_defaults))
            )
            text += '\n'.join('    %s' % s for s in proc_body)
            call = "%s = %s(%s)" % (', '.join(proc_results), proc_name, ', '.join(proc_param_names))
            proc_name, proc_param_names, proc_param_defaults, proc_results, proc_body = stack.pop()
            if proc_name is not None:
                proc_body.append(call)
            logging.debug(f'Defining a function:{text}')
            line_out = destination.send((tag, text))
        else:
            logging.error("Wrong JI state: tag=%s, line=%s" % (tag, line))

        tag, line = (yield line_out)

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
        tag, line = (yield line_out)
        line_out = line if not is_module or (tag in ['CODE', 'END_PROC']) else None

#
# JI-aware .ipynb import mechanism
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
        self.chain = fetch_tag(collect_proc(output_filter(is_module=True)))

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

        try:
            text = self.process_ipynb(nb)
            code = self.shell.input_transformer_manager.transform_cell(text)
            numbered_code ='\n'.join(['%4i %s' % (n+1, l) for n, l in enumerate(code.split('\n'))]) 
            exec(code, mod.__dict__)
            mod.__code__ = code
        except Exception as e:
            logging.error("Executing module code:\n" + numbered_code)
            raise e
        finally:
            self.shell.user_ns = save_user_ns
            return mod

    def process_ipynb(self, nb):
        """
        Pass the notebook through procedure collection filter and return parsed text.
        """
        lines_out = []

        for cell in nb.cells:
            cell_lines = cell.source.split('\n')
            if cell.cell_type == 'code':
                cell_lines_out = [l for l in (self.chain.send(l) for l in cell_lines) if l is not None]
                if len(cell_lines_out) > 0:
                    lines_out += cell_lines_out
                    lines_out.append('\n')
            elif cell.cell_type == 'markdown':
                lines_out += ['# ' + l.replace('\n', '') for l in cell_lines]
        return '\n'.join(lines_out)



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
