from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.org'), encoding='utf-8') as f:
    long_description = f.read()

config = {
    'name': 'iimport',
    'description': 'Tool for stressless import from IPython notebook files',
    'long_description': long_description,

    'author': 'krvkir',
    'author_email': 'krvkir@gmail.com',

    'url': '',
    'download_url': '',

    'version': '0.1.dev1',
    'install_requires': [
        'IPython',
        ],
    'packages': find_packages(exclude=['docs', 'contrib', 'tests']),
    'scripts': [],
}

setup(**config)
