def map_json_properties(m: Method) =
    Map("id" -> m.id
        , "code" -> m.code
        , "calls" -> m.callee.id.l
    )

@main def main(cpgFile: String) =
{
    importCpg(cpgFile)
    println(
        cpg.method
            .filterNot(m => m.isExternal || m.name.startsWith("<"))
            .map(m => map_json_properties(m))
            .toJsonPretty
    )
}

