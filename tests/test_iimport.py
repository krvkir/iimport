import unittest
import pytest
import os
import nbformat

import iimport
from iimport import fetch_tag, collect_proc, output_filter

import sample_notebook
path_nb = './sample_notebook.ipynb'


class TestNotebookLoader(unittest.TestCase):

    def test_object_creation(self):
        nbloader = iimport.NotebookLoader()

    def test_process_ipynb(self):
        with open(path_nb, 'r') as f:
            nb = nbformat.read(f, as_version=4)
        text = iimport.NotebookLoader.process_ipynb(nb)

    # def test_magic_cutter(self):
    #     nb = {
    #         'cells': [
    #             {
    #                 'cell_type': 'code',
    #                 'source': '%matplotlib inline',
    #             },
    #         ]
    #     }
    #     text = iimport.NotebookLoader.process_ipynb(nb)
    #     assert len(text) == 0

    def test_convert_ipynb(self):
        path_py = path_nb.rsplit('.', 1)[0] + '.py'

        if os.path.isfile(path_py):
            os.unlink(path_py)
        iimport.NotebookLoader.convert_ipynb(path_nb)
        assert os.path.isfile(path_py)
        os.rename(path_py, path_py + '_')


class TestImportIpynb(unittest.TestCase):

    def test_import_ipynb(self):
        assert type(sample_notebook) == type(os)

    def test_inner_function(self):
        assert 'outer_fn' in sample_notebook.__dict__
        assert 'inner_fn' in sample_notebook.__dict__

    def test_print_module_source(self):
        assert '__source__' in sample_notebook.__dict__

    def test_fn_in_example_is_declared(self):
        assert 'fn_in_example' in sample_notebook.__dict__

    def test_named_example_is_declared(self):
        assert '_example_x_plus_y' in sample_notebook.__dict__

    def test_skipped_fn(self):
        assert 'skipped_fn' not in sample_notebook.__dict__


class TestCodeTransformChain(unittest.TestCase):

    # def setUp(self):
    #     chain_opts = {'enabled': 0}
    #     chain = fetch_tag(collect_proc(output_filter()), opts=chain_opts)

    def test_chain_works(self):
        pass


if __name__ == '__main__':
    unittest.main()
