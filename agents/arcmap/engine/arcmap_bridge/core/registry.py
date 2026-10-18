# -*- coding: utf-8 -*-
ACTIONS = {}

def action(name):
    def decorator(func):
        ACTIONS[name] = func
        return func
    return decorator

def get(name):
    return ACTIONS.get(name)

def names():
    return sorted(ACTIONS.keys())
