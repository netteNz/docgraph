"""Fixture 5: two functions sharing only a same-named LOCAL variable.

Neither function's `config` is a module-level binding, so no symbol
edge should ever form between fn_a and fn_b.
"""


def fn_a():
    config = {"a": 1}
    return config["a"]


def fn_b():
    config = {"b": 2}
    return config["b"]
