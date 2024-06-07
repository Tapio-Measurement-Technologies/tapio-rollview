import numpy as np

def constant(limit):

    def f(profile):
        return limit

    return f


def rel_max(factor):

    def f(profile):
        return np.max(profile) * factor

    return f


def rel_min(factor):

    def f(profile):
        return np.min(profile) * factor

    return f


def rel_mean(factor):

    def f(profile):
        return np.mean(profile) * factor

    return f
