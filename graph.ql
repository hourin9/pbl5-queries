import go

from CallExpr call, Function caller, Function callee 
where
    caller = call.getEnclosingFunction().asFunction() and
    callee = call.getTarget()
select 
    caller.getQualifiedName() as source,
    callee.getQualifiedName() as target
