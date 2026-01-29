import go

from FuncDef f
select
    f.getName() as name,
    concat(f.getAParameter().getName(), ", ") as params,
    f.getLocation().getFile() as file

