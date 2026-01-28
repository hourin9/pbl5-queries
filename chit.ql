import go

from AstNode f
where
    f.getAPrimaryQlClass().toString() = "CallExpr"
select
    f.toString() as child_node,
    f.getLocation().getFile().getRelativePath() as file

