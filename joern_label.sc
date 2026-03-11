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

def long_param_list(func: Method) =
    func.parameter.length > 4

@main def main(cpgFile: String, project: String) =
{
    importCpg(cpgFile)

    cpg.method
        .filterNot(m => m.isExternal || m.name.startsWith("<"))
        .foreach { m =>
            val smell = List(
                long_name(m),
                long_method(m),
                long_param_list(m)
            )

            val smell_str = smell
                .map(if (_) 1 else 0 )
                .mkString(",")

            println(s"\"$project\",${m.id},\"${m.name}\",$smell_str")
        }
}

