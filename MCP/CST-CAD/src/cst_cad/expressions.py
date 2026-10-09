"""Evaluate the arithmetic subset used in geometry expressions, without eval."""
import ast
import math
import operator

_OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,
      ast.Div:operator.truediv,ast.Pow:operator.pow}
_FUNCS={name:getattr(math,name) for name in ('sqrt','sin','cos','tan','asin','acos','atan','exp','log','log10')}
_FUNCS.update(abs=abs,min=min,max=max)


def evaluate(expression, parameters):
    tree=ast.parse(expression.replace('^','**'),mode='eval')
    if sum(1 for _ in ast.walk(tree))>200:
        raise ValueError('expression too complex')
    def walk(node):
        if isinstance(node,ast.Expression):return walk(node.body)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return float(node.value)
        if isinstance(node,ast.Name):return float(math.pi if node.id=='pi' else parameters[node.id])
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return walk(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp) and type(node.op) in _OPS:
            left,right=walk(node.left),walk(node.right)
            if isinstance(node.op,ast.Pow) and abs(right)>100:raise ValueError('exponent too large')
            return _OPS[type(node.op)](left,right)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*(walk(a) for a in node.args))
        raise ValueError('unsupported expression syntax')
    result=walk(tree)
    if not isinstance(result,(int,float)) or not math.isfinite(result):raise ValueError('non-finite expression')
    return result
