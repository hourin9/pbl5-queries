import go

from CallExpr call, FuncDef caller,
    Function callee, Parameter params
where
    caller = call.getEnclosingFunction() and
    callee = call.getTarget() and
    params = caller.getAParameter()
select
    caller.getName() as source,
    concat(params.getName(), ", ") as caller_params,
    concat(params.getType().getName(), ", ") as caller_params_type,
    callee.getQualifiedName() as target

