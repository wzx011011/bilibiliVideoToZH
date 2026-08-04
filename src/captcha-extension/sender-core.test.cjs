const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./sender-core.js");

test("naturalCompare sorts numbered chunk names", () => {
  const names = ["10.txt", "02.txt", "1.txt"];
  names.sort(core.naturalCompare);
  assert.deepEqual(names, ["1.txt", "02.txt", "10.txt"]);
});

test("fingerprint is stable and includes text length", () => {
  assert.equal(core.fingerprint("课程字幕"), core.fingerprint("课程字幕"));
  assert.notEqual(core.fingerprint("课程字幕"), core.fingerprint("课程字幕。"));
  assert.match(core.fingerprint("课程字幕"), /^[0-9a-f]{8}:4$/);
});

test("validateItems rejects duplicate names and empty text", () => {
  assert.throws(() => core.validateItems([{ name: "01.txt", text: "" }]), /内容为空/);
  assert.throws(() => core.validateItems([
    { name: "01.txt", text: "一" },
    { name: "01.txt", text: "二" },
  ]), /重复/);
});

test("validateItems normalizes queue metadata", () => {
  const [item] = core.validateItems([{ name: "01.txt", text: "\uFEFF  第一块  ", chunkIndex: 1 }]);
  assert.equal(item.text, "第一块");
  assert.equal(item.chunkIndex, 1);
  assert.equal(item.status, "pending");
  assert.equal(item.fingerprint, core.fingerprint("第一块"));
});

test("exportableState omits prompt text", () => {
  const output = core.exportableState({
    runId: "run-1",
    status: "completed",
    index: 1,
    total: 1,
    items: [{
      name: "01.txt",
      text: "不应导出",
      chunkIndex: 1,
      fingerprint: "abc:4",
      status: "done",
      sentAt: "2026-08-05T00:00:00Z",
      replyAt: "2026-08-05T00:01:00Z",
      error: null,
    }],
  });
  assert.equal(output.items[0].name, "01.txt");
  assert.equal("text" in output.items[0], false);
});
