# 青岔矿区排水巡检交班

测图员登记分类格网与勘误。制图员核对确切修订的局部结果后发行。交班员在中心保存实收幅件。原站关闭后，值班员选择实际来件并签报，派工人员据此安排积水巡查和封闭干区复核。次班按原报告号领取定稿及首执，也可选用新的勘误件另签。

## 运行

使用 Python 3.11 标准库和 SQLite，从项目根目录运行。控制台在物化时提供完整回归入口。

```sh
python3 -B check_project.py
python3 -B demo.py
```

演示使用独立的原站和中心临时库。原左幅和右幅合选为两区一封闭，原左幅单选为两区零封闭。换用左幅勘误件后为一区零封闭。演示重开中心库并按两个原号复领。

## 格网与计数

`GridBounds(min_x, min_y, max_x, max_y)` 表示含端点的矩形整数格。`contains(x, y)` 检查归属，`coordinates()` 按行列顺序产生 `(x, y)`。同轮的幅件共用这一坐标系。分类只有 `wet` 和 `dry`。输入覆盖每个格，同坐标同分类的重复记录归一。非整数坐标、倒置幅界、缺格、越界和冲突分类拒绝。

积水区是所选湿格的八邻域连通分量。干格只经四邻域通行。能从分量内迈到一个未覆盖格的干区不计为封闭，即使该未覆盖格被其他入选幅件包围。空选幅签两项零。输入换序稳定，覆盖和分类相同的重新切幅保持两项计数。

## Python 接口

各站使用自己的 `sqlite3.Connection`。中心用另一条连接和独立数据库。写入接口拥有自己的事务，调用时连接应没有进行中的事务。应用负责关闭连接。

| 操作 | 调用与返回 |
| --- | --- |
| 班前初始化 | `survey.bootstrap.initialize_survey(db, station, seeds)` 建所需站表。每个种子为 `(round_id, tile_id, revision_id, bounds, cells)`。结果的 `added`、`reused` 和 `conflicts` 按输入次序记录各自的修订身份，冲突项附错误。站名是固定且全局分配的发行命名空间。 |
| 接纳 | `survey.revisions.ingest(db, round_id, tile_id, revision_id, bounds, cells)` 接收 `(x, y, classification)` 记录的迭代对象，返回含 `revision` 和 `created` 的结果。身份与归一内容均相同则复用。非法或冲突输入抛出 `InvalidGrid`。`get_revision` 查询确切修订，缺失抛出 `RevisionNotFound`。 |
| 局部核查 | `quality.tile_review.inspect(db, round_id, tile_id, revision_id)` 返回固定的 `TileCheck`，包含修订身份及 `wet_regions`、`enclosed_dry_regions`。缺失修订抛出 `RevisionNotFound`。 |
| 发行与补发 | `issue.publish.publish(db, round_id=..., tile_id=..., revision_id=...)` 返回 `(issue_id, original_bytes)`。用 `publish(db, issue_id=...)` 按号补发相同的返回类型及原字节。两种调用互斥。无效修订、未知发行号、坏源数据或写入错误抛出 `PublicationError`。 |
| 中心实收 | 先调用 `ReceiptStore(db).ensure_schema()` 和 `ReportStore(db).ensure_schema()`。`receipt.accept.accept(db, expected_round, original_bytes)` 返回 `ReceivedTile`，其 `receipt_id` 是选件用的正整数编号。精确重投复用编号。损坏、错轮或同号异件抛出 `ReceiptRejected`。 |
| 班次签报 | `review.finalize.sign(db, round_id, shift_id, receipt_ids)` 返回 `(SignedReport, FirstReceipt)`。实收号按集合处理并升序列示，每次成功签报取得独立报告号。错轮、缺件、共格、证据不足或写入失败抛出 `SignRejected`。 |
| 按号复领 | `review.archive.read(db, report_id)` 返回原报告和原首执。未知编号抛出 `ReportNotFound`。 |

调查轮、幅号、修订号、班次号及站名为非空、首尾无空白的可打印字符串。调查轮、幅号和修订号共同标识冻结格网。重复初始化重用完全相同的种子，原库中的勘误、复核和发行原件继续保留。有效勘误使用新的修订号。同一次签报固定实际实收号、发行号、幅号与来源修订。报告和首执必须同次提交才返回成功。

## V1 来件格式

`issue.envelope.V1Envelope(issue_id, round_id, tile_id, revision_id, bounds, body)` 是幅件值对象。`encode_v1` 返回原件字节，`decode_v1` 检查结构和完整性。外层为 UTF-8 JSON，含 `digest` 和 `payload` 两个字段。`payload` 是 JSON 文本，`digest` 是该文本 UTF-8 字节的 SHA-256 小写十六进制值。内层含 `version`、`issue_id`、`round_id`、`tile_id`、`revision_id`、`bounds` 和 `body`，版本为整数 1。幅界数组顺序为 `[min_x, min_y, max_x, max_y]`。标准编码采用排序对象键、紧凑分隔符和 ASCII 转义。实收按完整原件字节区分精确重投和同号异件。

正常正文含 `wet_regions`、`enclosed_dry_regions`、`boundary` 和 `links`。前两项为局部计数。`boundary` 按行列顺序列出每个边界格的 `[x, y, classification]`，每格一次。`links` 与边界行一一对应。标记在同一分类内从零按首次出现顺序编号，同标记表示经该幅格网连通。无边界格的组件以局部汇总计入。幅内逐格分类保存在原站。中心实收检查 V1 外层和来源，班次核定进一步检查正文和实选覆盖。
