import io.shiftleft.semanticcpg.language._
import ujson._

@main def main(cpgPath: String = "cpg.bin", outPath: String = "graph_dataset.json"): Unit = {
  println(s"Đang nạp CPG từ file: $cpgPath...")
  importCpg(cpgPath)

  println("Đang trích xuất Node Features...")
  val allMethods = cpg.method.filterNot(m => m.name.startsWith("<"))
  val nodesData = allMethods.map { method =>
    val lineEnd = method.lineNumberEnd.map(_.toInt).getOrElse(0)
    val lineStart = method.lineNumber.map(_.toInt).getOrElse(0)
    val loc = if (lineEnd > lineStart) lineEnd - lineStart + 1 else 0

    val cc = method.controlStructure.size + 1

    Obj(
      "id" -> method.id.toString,
      "name" -> method.name,
      "file_path" -> method.filename,
      "features" -> Obj(
        "loc" -> loc,
        "cyclomatic_complexity" -> cc,
        "num_params" -> method.parameter.size,
        "num_local_vars" -> method.local.size,
        "return_type" -> method.methodReturn.typeFullName,
        "fan_in" -> method.caller.size,
        "fan_out" -> method.callee.size,
        "code" -> method.code
      )
    )
  }.l

  println("Đang trích xuất Edges (Call Graph)...")
  val edgesData = cpg.call.map { call =>
    Obj(
      "source_id" -> call.method.id.toString,
      "target_id" -> call.callee.id.headOption.map(_.toString).getOrElse(""),
      "edge_type" -> "CALL"
    )
  }.filter(e => e("target_id").str != "").l

  // Đóng gói thành JSON và lưu ra file
  val finalJson = Obj(
    "nodes" -> nodesData,
    "edges" -> edgesData
  )
  
  os.write.over(os.Path(outPath, os.pwd), ujson.write(finalJson))
  println(s"Đã lưu kết quả trích xuất Joern tại: $outPath")
}
