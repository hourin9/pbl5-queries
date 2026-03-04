def long_name(dname: String): Boolean =
{
    val THRESHOLD = 20
    return dname.length >= THRESHOLD
}

def long_name(func: Method): Boolean = long_name(func.name)

def long_method(func: Method): Boolean =
{
    val THRESHOLD = 120
    return func.numberOfLines >= THRESHOLD
}

@main def main(cpgFile: String, project: String) =
{
    importCpg(cpgFile)

    cpg.method
        .filterNot(m => m.isExternal || m.name.startsWith("<"))
        .foreach { m =>
            val smell_type =
                if (long_name(m)) { 1 }
                else if (long_method(m)) { 2 }
                else { 0 }
            println(s"\"$project\",${m.id},\"${m.name}\",$smell_type")
        }
}

