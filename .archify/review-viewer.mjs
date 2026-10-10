/** 用 Archify 自带的真实浏览器接口检查本次产物；仅写入 .archify 中的补充证据。 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { ChromeVisualBrowser } from '/Users/anontokyo/.agents/skills/archify/bin/visual-check.mjs';

// 使用 Skill 同一浏览器封装，让本次补充检查针对最终 HTML。
const browser = new ChromeVisualBrowser('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
// 三个代表性路径均来自作者 JSON 中已存在的有向边。
const cases = [
  ['architecture', 'trivae-system', 'raw', 'canonical', 'core'],
  ['sequence', 'trivae-request', 'web', 'finalizer', 'runtime'],
  ['dataflow', 'trivae-evidence', 'raw', 'answer', 'retrieve'],
];
// 补充检查与 native finalize/visual-check receipt 分开保存。
const receipt = { evidence_kind: 'supplemental-viewer-interaction', checks: [] };
try {
  // 等待隔离 Chrome 进程完成附着，避免触碰用户已有浏览器会话。
  const session = await browser.sessionPromise;
  // 统一发送到刚建立的页面 session。
  const send = (method, args) => browser.cdp.send(method, args, session);
  // 固定普通桌面 viewport，使截图可以与原生检查对照。
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  for (const [type, slug, source, target, focus] of cases) {
    // 从本次交付目录定位最终 HTML，避免误读前一轮截图。
    const folder = path.resolve(`.archify/${type}-${slug}-20261010-104943`);
    // 浏览器只打开本地文件，不访问模型服务或业务数据库。
    await send('Page.navigate', { url: pathToFileURL(path.join(folder, `${slug}.html`)).href });
    // 等待该页面自身的 Viewer Runtime 就绪；超时显式暴露，不增加重试分支。
    const result = await send('Runtime.evaluate', {
      expression: `new Promise((resolve, reject) => {
        const started = performance.now();
        const check = () => {
          if (globalThis.Archify?.routeProbe && document.querySelector('.diagram-container > svg')) {
            document.fonts.ready.then(resolve);
          } else if (performance.now() - started > 5000) {
            reject(new Error('Archify Viewer Runtime did not become ready'));
          } else requestAnimationFrame(check);
        };
        check();
      })`, awaitPromise: true, returnByValue: true,
    });
    // Runtime.evaluate 的异常不是业务成功；保留异常并中止本轮检查。
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description);
    // 直接调用 Skill 公开交互 API，核对聚焦结果与作者定义的有向路径。
    const interaction = await send('Runtime.evaluate', {
      expression: `(() => {
        const focused = Archify.focus.set(${JSON.stringify(focus)}, { toggle: false });
        const active = Archify.focus.active();
        Archify.routeProbe.begin({ source: ${JSON.stringify(source)} });
        const reached = Archify.routeProbe.choose(${JSON.stringify(target)});
        const route = Archify.routeProbe.result();
        return { focused, active, reached, route, sourceBadges: document.querySelectorAll('[data-source-count]').length,
          sourceMetadataPresent: document.documentElement.outerHTML.includes('src/trivae/') };
      })()`, returnByValue: true,
    });
    // 对可交互能力执行真实断言，不仅检查 HTML 是否含有脚本字符串。
    const facts = interaction.result?.value;
    if (interaction.exceptionDetails || !facts?.focused || facts.active !== focus || !facts.reached || !facts.route || !facts.sourceMetadataPresent) {
      throw new Error(`Viewer interaction failed for ${type}: ${JSON.stringify(facts)}`);
    }
    // 清除短暂探索状态，让后续补充截图保留原始图表含义。
    await send('Runtime.evaluate', { expression: 'Archify.routeProbe.clear(); Archify.focus.clear();' });
    // 单独记录通过结果，保留 native receipt 的原始 provenance 字段。
    receipt.checks.push({ type, status: 'pass', focus, source, target, facts });
    if (type === 'sequence') {
      // 长时序图的 native 截图只覆盖顶部；滚动到后半段进行补充视觉核查。
      await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 950);' });
      // 连续两帧用于完成页面布局，不改变节点或关系。
      await send('Runtime.evaluate', { expression: 'new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))', awaitPromise: true });
      // 保存独立截图，避免覆盖 Archify 原生 artifact-bound capture。
      const capture = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      fs.writeFileSync(path.join(folder, 'sequence-lower-supplemental.png'), Buffer.from(capture.data, 'base64'));
    }
  }
  // 只有全部真实检查通过时才记录成功状态。
  receipt.status = 'pass';
  fs.writeFileSync('.archify/viewer-interaction-20261010-104943.json', `${JSON.stringify(receipt, null, 2)}\n`);
  console.log(JSON.stringify({ status: receipt.status, checks: receipt.checks.map(({ type, status }) => ({ type, status })) }));
} finally {
  // 释放本次检查创建的隔离浏览器资源。
  await browser.close();
}
