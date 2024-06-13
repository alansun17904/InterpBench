# InterpBench: Semi-Synthetic Transformers for Evaluating Mechanistic Interpretability Techniques

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.11518575.svg)](https://zenodo.org/doi/10.5281/zenodo.11518575)

This Python project provides a framework for creating and evaluating the models in InterpBench, a collection of semi-synthetic transformers with known circuits for evaluating mechanistic interpretability techniques

## Setup

This project can be setup by either downloading it and installing the dependencies, or by using the [Docker image](docker.io/iarcuschin/circuits-benchmark:latest). 
We use [Poetry](https://python-poetry.org/) to manage the dependencies, which you can install by following the instructions [here](https://python-poetry.org/docs/#installation).

Run the following Bash commands to download the project and its dependencies:
```bash
git clone --recurse-submodules git@github.com:FlyingPumba/circuits-benchmark.git
cd circuits-benchmark
poetry env use 3
poetry install
```

Then, to activate the virtual environment: `poetry shell`

## Usage

You can either use InterpBench by downloading the pre-trained models from [the Hugging Face repository](https://huggingface.co/cybershiptrooper/InterpBench) (see an example [here](DEMO_InterpBench.ipynb)), or by running the commands available in the Python framework.

### Training commands

The main two options for training models in the benchmark are "iit" and "ioi". The first option is used for training SIIT models based on Tracr circuits, and the second one for training a on a simplified version of the [IOI circuit](https://arxiv.org/abs/2211.00593). As an example, the following command will train a model on the Tracr circuit with id 3, for 30 epochs, using weights 0.4, 1, and 1, for SIIT loss, IIT loss, and behaviour loss, respectively.
```bash
./main.py train iit -i 3 --epochs 30 -s 0.4 -iit 1 -b 1 --early-stop
```
To check the arguments available for a specific command, you can use the `--help` flag. E.g., `./main.py train iit --help`

### Circuit discovery commands

There are two main circuit discovery techniques that are supported for now: [ACDC](https://arxiv.org/abs/2304.14997) and [SP](https://arxiv.org/abs/2104.03514). Some examples:

- Running ACDC on Tracr task 3: `./main.py run acdc -i 3 --threshold 0.71`
- Running SP on Tracr tasks 1 and 2: `./main.py run sp -i 1,2 --lambda-reg 0.5`
- Running edgewise SP on all Tracr tasks: `./main.py run sp --edgewise`

After running an algorith, the output can be found in the `results` folder.

### Evaluation commands

There are several evaluations that can be run using the framework. Options are: iit, iit_acdc, node_realism, ioi, ioi_acdc, and gt_node_realism.
See [EXPERIMENTS.md](EXPERIMENTS.md) for a list of the commands used in the paper's empirical study.

### Compilation commands

The benchmark CLI also provides a `compile` commmand that can be used to preemtively compile the RASP programs for all the cases into their corresponding Tracr/TransformerLends models. This can be useful to speed up the benchmark, as this compilation can take a long time.
To trigger this, run `./main.py compile`

## Tests

To run the tests, you can just run `pytest` in the root directory of the project. The tests for submodules are ignored by default.
If you want to run specific tests, you can use the `-k` flag: `pytest -k "get_cases_test"`.
