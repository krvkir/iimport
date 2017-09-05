from .context import iimport
from iimport.procedure import Procedure, Example


name = "myfac"
params_str = "n=8"
body_lines = """
# Call this recursively to calculate the factorial of n
res = n * myfac(n - 1)
"""
return_line = "return res"
meta = {'indent': ''}


def test_procedure_parse_param():
    assert Procedure._parse_param('a') == ('a', None)
    assert Procedure._parse_param('a=1') == ('a', '1')
    assert Procedure._parse_param('a[1]') == ('a_1', 'a[1]')
    assert Procedure._parse_param('a["key"]') == ('a_key', 'a["key"]')
    assert Procedure._parse_param('a.attr') == ('a_attr', 'a.attr')


def test_declare_procedure():
    proc = Procedure(name, params_str, meta)
    for line in body_lines.split('\n'):
        proc.add_line(line)
    text = proc.end(return_line)
    text = proc.call()

def test_declare_procedure_partly():
    assert False

def test_parameters_substitution_in_proc_body():
    assert False
