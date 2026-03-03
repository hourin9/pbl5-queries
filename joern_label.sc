def is_long_name(dname: String): Boolean = {
    val THRESHOLD = 20
    return dname.length >= THRESHOLD
}

@main def main(cpgFile: String, project: String) = {
    importCpg(cpgFile)

    cpg.method
        .filterNot(m => m.isExternal || m.name.startsWith("<"))
        .foreach { m =>
            val smell_type =
                if (is_long_name(m.name)) { 1 }
                else { 0 }
            println(s"\"$project\",${m.id},\"${m.name}\",$smell_type")
        }
}

