<!-- Stage 3-D B5: 强制 PR 描述统一格式. 设计 §12.4. -->

## 变化原因

<!-- 这个 PR 解决什么问题 / 引入什么能力. 一两句话, 不需要长篇大论. -->

## spec 章节 (如适用)

<!-- 触及 spec §X.Y 的内容请列出, 方便 review 时对照. 不适用就写 N/A. -->

- 设计文档 §

## 涉及变更类型

<!-- 多选, 删掉不适用的. -->

- [ ] 规则: 改 `config/rules.yaml` 阈值 / 新规则 / `custom_fn` 引用
- [ ] 流水线: 改 `aggregator/` / `rules/engine` / `ingest/` / `coordinator/`
- [ ] 通道: 改 `notify/` (dingtalk / webhook / SSE)
- [ ] HTTP 控制面: 改 `http/` (auth / admin / health / events)
- [ ] 部署: 改 `install.sh` / `run.sh` / `.env.example` / `Dockerfile`
- [ ] 文档: 仅改 README / spec / 注释
- [ ] CI / 测试: 改 `tests/` / `.github/workflows/` / `pyproject.toml`

## 回归与基线 (设计 §12.4)

<!-- 改了 rules.yaml / aggregator / engine / ingest / coordinator 必勾下面任一. -->

- [ ] **本地跑过 `pytest tests/replay/` 通过**, 无需 regen
- [ ] **跑过 `python scripts/regen_replay_baseline.py` regen 了 baseline**, 已 commit 进 PR; 变化原因:

  ```
  例: rules.yaml 的 inflight.wind_gust 阈值从 4.0 调回 14.0,
      verdicts 数从 1963 -> N, 全 DISPATCHED 数从 24 -> M. 符合预期.
  ```

- [ ] 与本 PR 无关 (改的是 docs / notify / http 等), 跳过 baseline 检查

## 静态门自查 (设计 §12.4)

<!-- CI 会自动跑 tests/ci/, 此处简单确认你心里有数. -->

- [ ] 没新增 `client.publish` / `mqtt.publish` 等 MQTT 下发调用 (§0.2)
- [ ] 没新增写 `topics/*.jsonl` 或 `raw_envelope` 之外的原始 envelope 落盘 (§0.4)
- [ ] 新增 `custom_fn:` 引用都已在 `CUSTOM_FN_WHITELIST` 注册 (§5.4)

## 测试 / 验证

<!-- 怎么验证这个 PR 真的 work. 至少一条. -->

- [ ] `pytest tests/unit tests/ci tests/integration/test_live_to_dingtalk.py` 通过
- [ ] (改了 rules / pipeline) `pytest tests/replay/` 通过
- [ ] (改了 http / channel) broadxt 真环境 `./run.sh stop live && ./run.sh live` + 灌测试帧验证
- [ ] 其它:

## 风险与回滚

<!-- 这个 PR 上线坏了的回滚路径. 写一句"./run.sh stop live && git revert <hash> && ./run.sh live"就行. -->
