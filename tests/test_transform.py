from .context import iimport
from iimport.transorm import Transformer

input_simple = """
a = 1
b = 2
%def func(a, b):
c = a + b
%return c
"""

output_simple = """
"""

input_nested = """
a = 1
b = 2

"""

output_nested = """
"""

piece_autodefine_args = """
%def func(a=1, b=2):
c = a + b
%return c
"""
