"""Tests for pep380.py."""

import unittest

from ndb import pep380
from ndb import task

class PEP380Tests(unittest.TestCase):
  """Test cases to verify the equivalence of yielding a generator to PEP 380.

  E.g. in a pre-PEP-380 world, this:

    @gwrap
    def g1():
      x = yield g2(0, 10)
      y = yield g2(5, 20)
      yield (x, y)

    @gwrap  # Optional
    def g2(a, b):
      for i in range(a, b):
        yield i
      raise Return(b - a)

    def main():
      assert list(g1()) == range(0, 10) + range(5, 20) + [(10, 15)]

  should be equivalent to this in a PEP-380 world:

    def g1():
      x = yield from g2(0, 10)
      y = yield from g2(5, 20)
      yield x, y

    def g2(a, b):
      yield from range(a, b)  # Maybe?
      return b - a

    def main():
      assert list(g1()) == range(0, 10) + range(5, 20) + [(10, 15)]
  """

  def testBasics(self):
    @pep380.gwrap
    def g1(a, b, c, d):
      x = yield g2(a, b)
      y = yield g2(c, d)
      yield (x, y)
    @pep380.gwrap
    def g2(a, b):
      for i in range(a, b):
        yield i
      raise task.Return(b - a)
    actual = []
    for val in g1(0, 3, 5, 7):
      actual.append(val)
    expected = [0, 1, 2,  5, 6, (3, 2)]
    self.assertEqual(actual, expected)

def main():
  unittest.main()

if __name__ == '__main__':
  main()
