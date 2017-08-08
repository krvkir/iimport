from iimport import save_ipynb_to_py

c = get_config()
c.FileContentsManager.post_save_hook = save_ipynb_to_py
