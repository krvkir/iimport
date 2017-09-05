import re
import pytest
from PyOrgMode.PyOrgMode import OrgDataStructure, OrgPlugin, OrgElement

from .context import iimport
from iimport.transorm import Transformer


class OrgCodeBlock(OrgPlugin):
    def __init__(self):
        OrgPlugin.__init__(self)
        self.regexp = re.compile("^(?:\s*?)(?:#\+(begin|end)_src)\s*(.*?)$")

    def _treat(self, current, line):
        codeblock = self.regexp.search(line)
        if codeblock:
            if codeblock.group(1) == 'end': # Ending code block
                current = current.parent
            elif codeblock.group(1) == 'begin': # Starting a code block
                current = self._append(
                    current, OrgCodeBlock.Element(codeblock.group(2)))
        else:
            self.treated = False

        return current

    class Element(OrgElement):
        TYPE = "CODEBLOCK"

        def __init__(self, lang):
            OrgElement.__init__(self)
            self.lang = lang


@pytest.fixture
def cases(path='./test_transform_cases.org'):
    base = OrgDataStructure()
    base.load_plugins(OrgCodeBlock())
    base.load_from_file(path)

    test_cases = {}
    for node in base.root.content:
        if 'test' not in node.tags:
            continue
        test_cases[node.heading.strip()] = test_case = {}
        for subnode in node.content:
            for item in subnode.content:
                if isinstance(item, OrgCodeBlock.Element):
                    test_case[subnode.heading.strip()] = ''.join(item.content)
                    break
    return test_cases


def test_all_cases(cases):
    for case_name, case in cases.items():
        print(case_name)
