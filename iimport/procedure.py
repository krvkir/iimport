from functools import reduce
import re
import logging
logger = logging.getLogger(__name__)


class Procedure(object):

    @staticmethod
    def _name_from_value(value):
        name = re.sub('[\'\"\[\]\.]+', '_', value)
        name = re.sub('_+$', '', name)
        return name

    @staticmethod
    def _parse_param(param):
        """
        Three cases are supported:
        1. one value looking like parameter name
        2. one value looking like parameter default value
           (like array or dict item, object property or simply a string)
        3. two values: parameter name and default value

        In case 2 we generate dummy variable name from its value
        (args.path -> args_path, args['path'] -> args__path__).

        Later in we'll substitute all entries of variable default value
        in function's body by the name of corresponding variable.
        """
        items = [s.strip() for s in param.split('=')]
        if len(items) == 1:
            default = items[0]
            name = Procedure._name_from_value(default)
            if name == default:
                default = None
        elif len(items) == 2:
            name, default = items
        else:
            raise Exception("Cannot process parameter definition: {param}"
                            .format(param=param))
        return name, default

    def __repr__(self):
        return self.__dict__.__repr__()

    def __init__(self, name, params_str, meta, ns={}):
        self.name = name

        self.params = [self._parse_param(param) for param in params_str.split(',')]
        self.param_names = [k for k, v in self.params]
        self.param_defaults = [v for k, v in self.params]
        self.param_substs = [(v, k) for k, v in self.params if v is not None]

        self.body = []
        self.ns = ns

        self.indent = meta.get('indent', 0)
        logger.debug("Procedure metadata from header:\n%s" % self)

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
            + [':param %s' % ('{k}={v}'.format(k=k, v=v) if v else k)
               for k, v in self.params]
            + ["Returns: %s" % ', '.join(self.results)]
            + ['"""']
            )

        params = ', '.join('{k}={v}'.format(k=k, v=v) if v else k
                           for k, v in self.params)
        text = "\ndef %s(%s):\n" % (self.name, params)
        text += '\n'.join('    %s' % s for s in comment_lines + self.body)
        return text

    def call(self, meta):
        params = ', '.join(v if v is not None else k for k, v in self.params)
        results = ', '.join(self.results)
        return ("{self.indent}{results} = {self.name}({params})"
                .format(self=self, results=results, params=params))


class Example(Procedure):
    """
    Example is a special case of the procedure:
    - it has no parameters and returns no values
    - its call is not inserted into the wrapping function when it ends
    - it can be nameless. If so, it does not produce a function

    Primary use case of examples: capture testing/debugging code inside something
    which should not be runned on import.

    Procedures declared inside examples are handled as any other procedures:
    they become functions on import.

    You can initialize variables, print dataframes, make plots and interactive
    widgets in the Example and do not bother it will run (and fail) when
    you import a procedure declared inside example.
    """

    def __init__(self, name=None, meta={}):
        return super(Example, self).__init__(name, '', meta)

    def end(self, *args, **kwargs):
        if self.name is None:
            # If the example is nameless, then do not export example as function
            return ''
        return super(Example, self).end(*args, **kwargs)

    def call(self, *args, **kwargs):
        if self.name is None:
            # If the example is nameless, then do not allow to call it
            return ''
        return super(Example, self).call(*args, **kwargs)


