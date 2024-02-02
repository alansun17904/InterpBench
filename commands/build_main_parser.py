import argparse

from commands.algorithms import run_algorithm
from commands.analysis import perform_analysis
from commands.compilation import compile_benchmark
from commands.train import train


def build_main_parser():
  # define commands for our main script.
  parser = ArgumentParserWithOriginals()
  subparsers = parser.add_subparsers(dest="command")
  subparsers.required = True

  # Setup command arguments
  compile_benchmark.setup_args_parser(subparsers)
  run_algorithm.setup_args_parser(subparsers)
  perform_analysis.setup_args_parser(subparsers)
  train.setup_args_parser(subparsers)

  return parser


class ArgumentParserWithOriginals(argparse.ArgumentParser):
  """ArgumentParser that stores the original arguments."""
  def parse_args(self, *args, **kwargs):
    original_args = list(args[0])
    parsed_args = super().parse_args(*args, **kwargs)
    parsed_args.original_args = original_args
    return parsed_args

  def parse_known_args(self, *args, **kwargs):
    original_args = list(args[0])
    parsed_args, unknown_args = super().parse_known_args(*args, **kwargs)
    parsed_args.original_args = original_args
    return parsed_args, unknown_args
