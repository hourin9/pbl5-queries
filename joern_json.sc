def map_json_properties(m: Method) =
    Map("id" -> m.id, "code" -> m.code)

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

