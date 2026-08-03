# 处理结果生成在这里

每次运行会建立一个以 `run_id` 命名的子目录，其中包括：

- `<原文件名>_processed.csv`：NameMap 输入的处理结果。
- `<原文件名>_standardized.csv`：浓度表输入的标准化结果。
- `review_queue.csv`：跳过、无候选或仍需复核的项目。
- `goal_coverage.csv`：客户目标是否覆盖，以及AI置信度、身份可信度、目标符合度和综合分。
- `matching_explanation.txt`：可直接提供给客户的偏好尺度和各评分字段说明。

详细检查点和审计记录仍保存在项目根目录的 `runs/`。
