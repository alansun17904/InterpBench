from typing import Set

from benchmark import vocabs
from benchmark.benchmark_case import BenchmarkCase
from tracr.rasp import rasp


class Case00030(BenchmarkCase):
  def get_program(self) -> rasp.SOp:
    return make_numeric_range_tagging(rasp.tokens, 10, 20)

  def get_vocab(self) -> Set:
    return vocabs.get_str_numbers_vocab(min=0, max=30)


def make_numeric_range_tagging(sop: rasp.SOp, lower_bound: int, upper_bound: int) -> rasp.SOp:
    """
    Tags numeric tokens in a sequence based on whether they fall within a given range.

    Example usage:
      range_tagging = make_numeric_range_tagging(rasp.tokens, 10, 20)
      range_tagging(["5", "15", "25", "20"])
      >> [False, True, False, True]
    """
    range_tagging = rasp.Map(
        lambda x: lower_bound <= int(x) <= upper_bound if x.isdigit() else False, sop)
    return range_tagging
