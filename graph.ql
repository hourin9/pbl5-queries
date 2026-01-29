import go

from CallExpr call, FuncDef caller, Function callee
where
    caller = call.getEnclosingFunction() and
    callee = call.getTarget()
select
    caller.getName() as source,
    callee.getQualifiedName() as target

