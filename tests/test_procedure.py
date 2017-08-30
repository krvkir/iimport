from .context import iimport
from iimport.procedure import Procedure, Example


name = "myfac"
params_line = "n"
body_lines = """
# Call this recursively to calculate the factorial of n
res = n * myfac(n - 1)
"""
return_line = "return res"
meta = {'indent': 0}


def test_declare_procedure():
    proc = Procedure(name, params_str)
