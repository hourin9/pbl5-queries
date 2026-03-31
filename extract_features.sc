import io.shiftleft.semanticcpg.language._
import ujson._

@main def main(cpgFile: String = "cpg.bin"): Unit = {
  // println(s"Đang nạp CPG từ file: $cpgFile...")
  importCpg(cpgFile)

  // println("Đang trích xuất Node Features...")
  // 1. Khởi tạo danh sách chứa dữ liệu các node (hàm)
  val allMethods = cpg.method.filterNot(m => m.isExternal || m.name.startsWith("<"))
  val nodesData = allMethods.map { method =>
    val lineEnd = method.lineNumberEnd.map(_.toInt).getOrElse(0)
    val lineStart = method.lineNumber.map(_.toInt).getOrElse(0)
    val loc = if (lineEnd > lineStart) lineEnd - lineStart + 1 else 0

    val cc = method.controlStructure.size + 1

    Obj(
      "id" -> method.id.toString,
      "name" -> method.name,
      "features" -> Obj(
        "loc" -> loc,
        "cyclomatic_complexity" -> cc,
        "num_params" -> method.parameter.size,
        "num_local_vars" -> method.local.size,
        "return_type" -> method.methodReturn.typeFullName,
        "fan_in" -> method.caller.size,
        "fan_out" -> method.callee.size,
        "code" -> method.code,
      )
    )
  }.l

  // println("Đang trích xuất Edges (Call Graph)...")
  val edgesData = cpg.call.map { call =>
    Obj(
      "source_id" -> call.method.id.toString,
      "target_id" -> call.callee.id.headOption.map(_.toString).getOrElse(""),
      "edge_type" -> "CALL"
    )
  }.filter(e => e("target_id").str != "").l

  // 3. Đóng gói thành JSON
  val finalJson = Obj(
    "nodes" -> nodesData,
    "edges" -> edgesData
  )

  // 4. Ghi trực tiếp ra file bằng Scala
  println(ujson.write(finalJson, indent = 2))
}
