/*
 * WMA301 recovery Web UI (single page) for the U-Boot failsafe httpd of
 * Yuzhii0718/uboot-airoha-mediatek (2026.10). Read-only backup and RAM APIs:
 *   /version /sysinfo /upload /result /last-error /reboot /reboot-failsafe /boot
 *   /backup/info /backup/main /env/list /env/set /env/unset
 *   /console/exec /console/poll /console/clear /ubi/info /ubi/volumes /ubi/remove
 */
"use strict";

const S = { feat: {}, ver: "", sys: null, env: null, route: "", busy: false };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
	(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const human = (n) => n >= 1048576 ? (n / 1048576).toFixed(2) + " MiB" :
	n >= 1024 ? (n / 1024).toFixed(0) + " KiB" : n + " B";

const ROUTES = [
	{ id: "firmware", title: "固件升级" },
	{ id: "initramfs", title: "内存启动" },
	{ id: "uboot", title: "U-Boot 更新" },
	{ id: "backup", title: "备份", feat: "backup" },
	{ id: "env", title: "环境变量", feat: "env" },
	{ id: "ubi", title: "UBI", feat: "ubi" },
	{ id: "console", title: "命令行", feat: "console", danger: true },
	{ id: "system", title: "系统" },
];

/* ------------------------------------------------------------ http ---- */
async function get(url, asJson) {
	const r = await fetch(url, { cache: "no-store" });
	if (!r.ok) throw new Error(url + " HTTP " + r.status);
	return asJson ? r.json() : r.text();
}
async function post(url, fields, asJson) {
	const fd = new FormData();
	for (const k in fields) fd.append(k, fields[k]);
	const r = await fetch(url, { method: "POST", body: fd, cache: "no-store" });
	const text = await r.text();
	if (!r.ok) throw new Error(text || ("HTTP " + r.status));
	return asJson ? JSON.parse(text) : text;
}
async function exists(url) {
	try { return (await fetch(url, { cache: "no-store" })).ok; } catch (e) { return false; }
}
function uploadXhr(field, file, onProgress) {
	return new Promise((resolve, reject) => {
		const fd = new FormData();
		fd.append(field, file);
		const x = new XMLHttpRequest();
		x.upload.onprogress = (e) => { if (e.total) onProgress(e.loaded / e.total); };
		x.onload = () => x.status === 200 ? resolve(x.responseText) : reject(new Error("HTTP " + x.status));
		x.onerror = () => reject(new Error("网络错误，连接已断开"));
		x.open("POST", "/upload");
		x.send(fd);
	});
}
function parseFailure(text) {
	const lines = String(text).split("\n");
	const out = { code: "", error: "" };
	for (const l of lines) {
		if (l.indexOf("code:") === 0) out.code = l.slice(5);
		if (l.indexOf("error:") === 0) out.error = l.slice(6);
	}
	return out;
}
async function lastError() {
	try { return await get("/last-error", true); } catch (e) { return { code: 0, error: "" }; }
}

/* ------------------------------------------------------------ modal --- */
function modal(html) { $("modal_box").innerHTML = html; $("modal").classList.add("on"); }
function closeModal() { $("modal").classList.remove("on"); }
function confirmBox(title, body, okText, danger, word) {
	return new Promise((resolve) => {
		modal(`<h3>${esc(title)}</h3><div>${body}</div>` +
			(word ? `<p>请输入 <b>${esc(word)}</b> 确认：</p><input type="text" id="cf_word">` : "") +
			`<div class="row" style="justify-content:flex-end">
			<button class="btn" id="cf_no">取消</button>
			<button class="btn ${danger ? "dng" : "pri"}" id="cf_ok">${esc(okText)}</button></div>`);
		$("cf_no").onclick = () => { closeModal(); resolve(false); };
		$("cf_ok").onclick = () => {
			if (word && $("cf_word").value.trim() !== word) { $("cf_word").focus(); return; }
			closeModal(); resolve(true);
		};
	});
}
function errorHtml(title, info) {
	return `<div class="note err"><b>${esc(title)}</b>` +
		(info && (info.error || info.code) ? `<div class="mono">${esc(info.error || "")}${info.code ? "（代码 " + esc(info.code) + "）" : ""}</div>` : "") +
		`</div>`;
}

/* ------------------------------------------------------------ shell --- */
async function boot() {
	try { S.ver = (await get("/version")).trim(); } catch (e) { S.ver = ""; }
	try { S.sys = await get("/sysinfo", true); } catch (e) { S.sys = null; }
	const [u, b, e, c, ubi] = await Promise.all([
		exists("/uboot.html?probe=1"), exists("/backup/info"), exists("/env/list"),
		exists("/console.html?probe=1"), exists("/ubi/volumes")]);
	S.feat = { uboot: u, backup: b, env: e, console: c, ubi: ubi };
	if (e) { try { S.env = parseEnv(await get("/env/list")); } catch (x) { S.env = null; } }
	const model = S.sys && S.sys.board && S.sys.board.model;
	$("top_model").textContent = model || "U-Boot Web Recovery";
	$("top_ver").textContent = (S.ver.match(/U-Boot \S+/) || ["U-Boot"])[0];
	$("top_ver").title = S.ver;
	renderFoot();
	window.addEventListener("hashchange", route);
	$("modal").addEventListener("click", (ev) => { if (ev.target.id === "modal" && !S.busy) closeModal(); });
	route();
}
function renderNav() {
	$("nav").innerHTML = ROUTES.filter((r) => !r.feat || S.feat[r.feat]).map((r) =>
		`<a href="#${r.id}" class="${r.id === S.route ? "on" : ""} ${r.danger ? "danger" : ""}">${r.title}</a>`).join("");
}
function renderFoot() {
	$("foot").innerHTML =
		`<div class="mono">${esc(S.ver)}</div>
		<div>底层：<a href="https://github.com/Yuzhii0718/uboot-airoha-mediatek" target="_blank" rel="noopener">Yuzhii0718/bl-mt798x-dhcpd</a>
		（基于 <a href="https://github.com/hanwckf/bl-mt798x" target="_blank" rel="noopener">hanwckf/bl-mt798x</a>、MediaTek U-Boot / ATF）
		· WMA301 适配与界面：<a href="https://github.com/pzcn/bl-mt798x-dhcpd/tree/feat/wma301-uboot-2026.10" target="_blank" rel="noopener">pzcn/bl-mt798x-dhcpd</a>
		· GPL-2.0</div>`;
}
function route() {
	if (S.busy) return;
	let id = (location.hash || "#firmware").slice(1);
	if (["flashing", "booting", "fail", "reboot"].indexOf(id) >= 0) id = id === "reboot" ? "system" : "firmware";
	const r = ROUTES.find((x) => x.id === id && (!x.feat || S.feat[x.feat])) || ROUTES[0];
	S.route = r.id;
	renderNav();
	VIEWS[r.id]();
}
function view(html) { $("view").innerHTML = html; }
function parseEnv(text) {
	const o = {};
	String(text).split("\n").forEach((l) => { const i = l.indexOf("="); if (i > 0) o[l.slice(0, i)] = l.slice(i + 1); });
	return o;
}

/* --------------------------------------------------- upload pipeline -- */
function sniff(buf) {
	const b = new Uint8Array(buf);
	const s = (o, n) => String.fromCharCode.apply(null, b.slice(o, o + n));
	if (b[0] === 0xd0 && b[1] === 0x0d && b[2] === 0xfe && b[3] === 0xed) return "FIT 镜像（.itb）";
	if (s(257, 5) === "ustar") return "sysupgrade 包（tar）";
	if (s(0, 7) === "WMABL33") return "WMA301 BL33 更新包";
	if (b[0] === 0xfd && s(1, 4) === "7zXZ") return "xz 压缩数据";
	return "";
}
function dropZone(id, accept, hint) {
	return `<label class="drop" id="${id}_drop"><input type="file" id="${id}_file" accept="${accept}">
		<b>点击选择文件，或把文件拖到这里</b><span class="sub">${hint}</span></label>`;
}
function bindDrop(id, onFile) {
	const d = $(id + "_drop"), f = $(id + "_file");
	f.onchange = () => f.files[0] && onFile(f.files[0]);
	d.ondragover = (e) => { e.preventDefault(); d.classList.add("over"); };
	d.ondragleave = () => d.classList.remove("over");
	d.ondrop = (e) => { e.preventDefault(); d.classList.remove("over"); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); };
}
function steps(cur) {
	return `<div class="steps">${["选择文件", "上传校验", "执行", "完成"].map((t, i) =>
		`<span class="${i < cur ? "done" : i === cur ? "on" : ""}">${i < cur ? "✓ " : ""}${t}</span>`).join("")}</div>`;
}

/* kind: firmware | initramfs | fip */
async function runUpload(kind, file, area) {
	if (kind !== "initramfs" && kind !== "fip") {
		area.innerHTML = errorHtml("通用刷写已禁用", { error: "仅允许内存启动 initramfs 或有严格校验的 WMABL33 更新。" });
		return;
	}
	const titles = { firmware: "固件", initramfs: "内存启动镜像", fip: "U-Boot 更新包" };
	S.busy = true;
	try {
		area.innerHTML = steps(1) + `<div><b>${esc(file.name)}</b> · ${human(file.size)}</div>
			<div class="bar"><i id="up_bar"></i></div><div class="sub" id="up_txt">正在上传…</div>`;
		const resp = await uploadXhr(kind, file, (p) => {
			$("up_bar").style.width = (p * 100).toFixed(0) + "%";
			$("up_txt").textContent = "正在上传 " + (p * 100).toFixed(0) + "%";
		});
		if (resp.split("\n")[0].trim() === "fail") {
			S.busy = false;
			area.innerHTML = steps(1) + errorHtml("校验未通过，没有写入任何内容", parseFailure(resp)) +
				`<div class="row"><button class="btn" onclick="route()">重新选择</button></div>`;
			return;
		}
		const parts = resp.trim().split(" ");
		const msg = kind === "initramfs" ? "确认后设备会从内存启动这个镜像，flash 不会被修改。" :
			kind === "fip" ? "将通过专用写入器替换原厂 FIP 中的 BL33，保留 BL2/BL31。<b>必须提前备份 FIP，并已通过 TTL 临时授权；写入失败或断电仍可能变砖。</b>" :
			"将写入 UBI 区域（0x700000 之后）。引导区、出厂信息和无线校准数据不会被修改。写入期间请勿断电。";
		area.innerHTML = steps(1) + `<div class="note ok">上传完成，校验通过。</div>
			<div class="kv"><div>文件</div><div>${esc(file.name)}</div><div>大小</div><div>${human(+parts[0] || file.size)}</div>
			<div>MD5</div><div class="mono">${esc(parts[1] || "")}</div></div>
			<div class="note ${kind === "fip" ? "warn" : ""}">${msg}</div>
			<div class="row"><button class="btn" id="up_cancel">取消</button>
			<button class="btn big ${kind === "fip" ? "dng" : "pri"}" id="up_go">${kind === "initramfs" ? "启动" : "开始写入"}</button></div>`;
		const go = await new Promise((res) => { $("up_go").onclick = () => res(true); $("up_cancel").onclick = () => res(false); });
		if (!go) { S.busy = false; route(); return; }
		if (kind === "fip" && !(await confirmBox("确认更新 U-Boot", "写入大约需要几秒钟，期间绝对不要断电。", "确认更新", true, "更新"))) {
			S.busy = false; route(); return;
		}
		area.innerHTML = steps(2) + `<h3>${kind === "initramfs" ? "正在准备启动…" : "正在写入" + titles[kind] + "…"}</h3>
			<div class="bar indet"><i></i></div><div class="note warn">请勿断电，不要关闭本页面。</div>`;
		const result = await get("/result");
		if (result.split("\n")[0].trim() !== "success") {
			const info = parseFailure(result);
			const le = (!info.error && !info.code) ? await lastError() : info;
			S.busy = false;
			area.innerHTML = steps(2) + errorHtml("写入失败", le) +
				`<div class="row"><button class="btn" onclick="route()">返回</button></div>`;
			return;
		}
		S.busy = false;
		if (kind === "initramfs") {
			area.innerHTML = steps(4) + `<div class="note ok"><b>正在从内存启动。</b>约 1 分钟后系统就绪，
				通常可以访问 <a href="http://192.168.1.1/">http://192.168.1.1/</a>（以镜像的默认设置为准）。flash 未被修改，断电后会回到原系统或恢复模式。</div>`;
			return;
		}
		area.innerHTML = steps(4) + `<div class="note ok"><b>${titles[kind]}写入成功。</b></div>
			<div class="row">${kind === "firmware" ? `<button class="btn big pri" onclick="doBoot('boot')">启动系统</button>` : ""}
			<button class="btn ${kind === "firmware" ? "" : "big pri"}" onclick="doBoot('reboot')">重启</button></div>`;
	} catch (e) {
		S.busy = false;
		area.innerHTML = errorHtml("操作中断：" + e.message, null) +
			`<div class="row"><button class="btn" onclick="route()">返回</button></div>`;
	}
}

async function doBoot(mode) {
	const urls = { reboot: "/reboot", failsafe: "/reboot-failsafe", boot: "/boot" };
	const texts = { reboot: "正在重启…", failsafe: "正在重启并回到恢复模式…", boot: "正在启动系统…" };
	try { await get(urls[mode]); } catch (e) { /* device may already be going down */ }
	view(`<div class="card"><h2>${texts[mode]}</h2><div class="bar indet"><i></i></div>
		<p class="sub" id="wait_txt">${mode === "failsafe" ? "恢复模式重新可用后会自动刷新本页。" :
		"系统启动需要一点时间；之后请访问系统自己的管理地址。"}</p></div>`);
	if (mode === "failsafe") {
		const t0 = Date.now();
		const poll = async () => {
			if (await exists("/version")) { location.href = "/"; return; }
			if (Date.now() - t0 < 120000) setTimeout(poll, 2000);
			else $("wait_txt").textContent = "超时：请确认设备已重启，并手动刷新页面。";
		};
		setTimeout(poll, 4000);
	}
}

/* ------------------------------------------------------------ views --- */
const VIEWS = {};

VIEWS.firmware = () => {
	const sys = S.sys || {};
	const mac = (S.sys && S.sys.mac) || (S.env && S.env.ethaddr) || "—";
	view(`<div class="grid">
		<div class="stat"><div class="k">设备</div><div class="v">${esc((sys.board && sys.board.model) || "WMA301 V2")}</div></div>
		<div class="stat"><div class="k">U-Boot</div><div class="v">${esc((S.ver.match(/U-Boot \S+/) || ["2026.10"])[0])}</div></div>
		<div class="stat"><div class="k">MAC</div><div class="v mono">${esc(mac)}</div></div>
		<div class="stat"><div class="k">内存</div><div class="v">${sys.ram && sys.ram.size ? human(sys.ram.size) : "—"}</div></div>
		</div>
		<div class="card" style="margin-top:16px"><h2>固件升级</h2>
		<div class="note warn"><b>实验性 U-Boot 2026.10：</b>为保护原厂 BL2、BL31 和 NAND 分区，本版本禁用全部 Web 持久化写入。当前不能从此页面刷入 ImmortalWrt。</div>
		<p class="sub"><b>2026.10 实验版有意禁用网页直接刷 sysupgrade.itb。</b>首次安装 ImmortalWrt 应先从 initramfs 内存启动，再在 Linux 里执行经过验证的 sysupgrade。升级过程中须保留 UBI 内 ubootenv、ubootenv2 两个约 124 KiB 的环境卷。Web BL33 更新属于单独功能，不等同于固件升级。</p>
		<div class="row"><a class="btn big pri" href="#initramfs">进入内存启动</a><a class="btn" href="#uboot">U-Boot 更新说明</a></div></div>`);
};

async function precheck(file, kind, area) {
	if (kind !== "initramfs" && kind !== "fip") {
		area.innerHTML = errorHtml("通用刷写已禁用", { error: "只允许 initramfs / WMABL33 两种操作。" });
		return;
	}
	const head = await file.slice(0, 512).arrayBuffer();
	const type = sniff(head);
	if (kind === "fip") {
		const b = new Uint8Array(head);
		const txt = String.fromCharCode.apply(null, b.slice(16, 48)).replace(/\0+$/, "");
		if (type !== "WMA301 BL33 更新包") {
			area.innerHTML = steps(0) + errorHtml("这不是 U-Boot 更新包", { error: "请选择 WMA301_BL33_UPDATE.bin（不是 .bin 格式的 u-boot、也不是 fip.bin）" }) +
				`<div class="row"><button class="btn" onclick="route()">重新选择</button></div>`;
			return;
		}
		if (!(await confirmBox("U-Boot 更新包", `<div class="kv"><div>文件</div><div>${esc(file.name)}</div>
			<div>适用设备</div><div class="mono">${esc(txt)}</div><div>大小</div><div>${human(file.size)}</div></div>`, "上传并校验"))) return;
	} else if (!type || type === "WMA301 BL33 更新包") {
		if (!(await confirmBox("文件类型无法识别",
			`<p>${esc(file.name)} 看起来不是 FIT 或 sysupgrade 固件${type ? "（它是 " + esc(type) + "）" : ""}。</p><p>仍然上传让 U-Boot 校验吗？校验不通过不会写入。</p>`,
			"仍然上传"))) return;
	}
	runUpload(kind, file, area);
}

VIEWS.initramfs = () => {
	view(`<div class="card"><h2>内存启动</h2>
		<p class="sub">上传 initramfs / recovery 镜像（例如 <span class="mono">*-initramfs-recovery.itb</span>），
		设备直接从内存运行它，<b>不写 flash</b>。适合测试新固件或救急。</p>
		<div id="ir_area">${steps(0)}${dropZone("ir", ".itb,.bin", "通常是 *-initramfs-recovery.itb")}</div></div>`);
	bindDrop("ir", (f) => precheck(f, "initramfs", $("ir_area")));
};

VIEWS.uboot = () => {
	view(`<div class="card"><h2>U-Boot 更新 · WMABL33 v1</h2>
		<p class="sub">只接受 <span class="mono">WMA301_BL33_UPDATE.bin</span>（128 字节 WMABL33 v1 头 + XZ/CRC32 压缩 BL33）。服务端将验证板型、两个 SHA-256、加载地址及原厂 FIP 结构，保留原厂 BL2/BL31。</p>
		<div class="note warn"><b>实验性功能，具有变砖风险：</b>只会修改原厂 FIP 中的 BL33；如果写入中断或新 BL33 无法启动，仍可能需要 TTL/BootROM 救援。请提前备份原厂 FIP。</div>
		<div class="note warn"><b>原厂 FIP 起点为 0x20000。</b>此 BL33 更新器只支持已经刷过自定义 U-Boot、原 FIP 实际占用不超过三个 128 KiB 擦除块的设备。原厂首次刷入必须使用 Toolbox 或经过验证的 TTL 救援流程。<b>务必先备份原厂 FIP；写入须在 TTL 中临时授权。</b>切勿把 WMABL33 包当作完整 FIP 直接写入 NAND。</div>
		<div id="ub_area">${steps(0)}${dropZone("ub", ".bin", "仅支持 WMA301_BL33_UPDATE.bin")}</div>
		<p class="sub" style="margin-top:12px">当前：<span class="mono">${esc(S.ver)}</span></p></div>`);
	bindDrop("ub", (file) => precheck(file, "fip", $("ub_area")));
};

VIEWS.backup = async () => {
	view(`<div class="card"><h2>备份</h2><p class="sub">只读备份 bl2、fip、factory_info、art、config。<b>art</b> 包含无线校准数据；出厂信息及 config 可能包含设备标识或敏感配置。请断开 WAN、使用直连 LAN 备份并妥善保存。</p>
		<div id="bk_list">正在读取分区表…</div></div>`);
	try {
		const info = await get("/backup/info", true);
		const parts = (info.mtd && info.mtd.parts) || [];
		const mac = ((S.sys && S.sys.mac) || (S.env && S.env.ethaddr) || "wma301").replace(/:/g, "").toUpperCase();
		$("bk_list").innerHTML = `<table><thead><tr><th>分区</th><th class="r">大小</th><th></th></tr></thead><tbody>` +
			parts.map((p, i) => `<tr><td>${esc(p.master ? p.name + "（整片）" : p.name)}
				${p.name === "art" || p.name === "factory_info" ? '<span class="chip warn">重要</span>' : ""}</td>
				<td class="r">${human(p.size)}</td><td class="r"><button class="btn sm" data-i="${i}">下载</button>
				<span class="sub" id="bk_s${i}"></span></td></tr>`).join("") + `</tbody></table>`;
		$("bk_list").querySelectorAll("button[data-i]").forEach((b) => {
			b.onclick = () => downloadPart(parts[+b.dataset.i], mac, $("bk_s" + b.dataset.i), b);
		});
	} catch (e) {
		$("bk_list").innerHTML = errorHtml("读取分区表失败：" + e.message, null);
	}
};

async function downloadPart(p, mac, status, btn) {
	btn.disabled = true;
	try {
		const fd = new FormData();
		fd.append("mode", "part"); fd.append("storage", "mtd"); fd.append("target", p.name);
		const r = await fetch("/backup/main", { method: "POST", body: fd });
		if (!r.ok) throw new Error("HTTP " + r.status);
		const reader = r.body.getReader();
		const chunks = []; let got = 0;
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			chunks.push(value); got += value.length;
			status.textContent = (got / p.size * 100).toFixed(0) + "%";
		}
		if (got !== p.size) throw new Error("长度不对：" + got + " / " + p.size);
		const a = document.createElement("a");
		a.href = URL.createObjectURL(new Blob(chunks, { type: "application/octet-stream" }));
		a.download = `${mac}_${p.name}.bin`;
		document.body.appendChild(a); a.click(); a.remove();
		status.textContent = "✓ 已保存";
	} catch (e) {
		status.textContent = "失败：" + e.message;
	}
	btn.disabled = false;
}

const ENV_HINTS = {
	ethaddr: "网口 MAC。开机时会从 factory_info 自动读取（设 mac_from_mtd=0 可改为手动）",
	mac_from_mtd: "设为 0：不再从 flash 读取 MAC，使用 ethaddr",
	glbtn_key: "上电检测的按键，默认 reset,mesh；reset 键始终作为兜底",
	failsafe_auto_reboot: "设为 1：刷写成功后自动重启",
	bootcmd: "启动命令（WMA301 由设备树固定，修改一般无效）",
};
VIEWS.env = async () => {
	view(`<div class="card"><h2>环境变量</h2><p class="sub">修改后立即保存到 UBI 卷 ubootenv/ubootenv2。</p>
		<div id="env_list">正在读取…</div>
		<h3 style="margin-top:18px">新增 / 修改</h3>
		<div class="grid"><input type="text" id="env_n" placeholder="名称"><input type="text" id="env_v" placeholder="值"></div>
		<div class="row"><button class="btn pri" id="env_save">保存</button><span class="sub" id="env_msg"></span></div></div>`);
	const load = async () => {
		try {
			S.env = parseEnv(await get("/env/list"));
			const keys = Object.keys(S.env).sort((a, b) => (ENV_HINTS[b] ? 1 : 0) - (ENV_HINTS[a] ? 1 : 0) || a.localeCompare(b));
			$("env_list").innerHTML = `<table><tbody>` + keys.map((k) => `<tr><td class="mono" style="width:30%">${esc(k)}
				${ENV_HINTS[k] ? `<div class="hint">${esc(ENV_HINTS[k])}</div>` : ""}</td>
				<td class="mono">${esc(S.env[k])}</td><td class="r" style="white-space:nowrap">
				<button class="btn sm" data-e="${esc(k)}">编辑</button> <button class="btn sm" data-d="${esc(k)}">删除</button></td></tr>`).join("") + `</tbody></table>`;
			$("env_list").querySelectorAll("[data-e]").forEach((b) => b.onclick = () => {
				$("env_n").value = b.dataset.e; $("env_v").value = S.env[b.dataset.e]; $("env_v").focus();
			});
			$("env_list").querySelectorAll("[data-d]").forEach((b) => b.onclick = async () => {
				if (!(await confirmBox("删除变量", `删除 <b class="mono">${esc(b.dataset.d)}</b>？`, "删除", true))) return;
				try { await post("/env/unset", { name: b.dataset.d }); load(); } catch (e) { $("env_msg").textContent = "失败：" + e.message; }
			});
		} catch (e) { $("env_list").innerHTML = errorHtml("读取失败：" + e.message, null); }
	};
	$("env_save").onclick = async () => {
		const n = $("env_n").value.trim();
		if (!n) return;
		try { await post("/env/set", { name: n, value: $("env_v").value }); $("env_msg").textContent = "已保存"; load(); }
		catch (e) { $("env_msg").textContent = "失败：" + e.message; }
	};
	load();
};

VIEWS.ubi = async () => {
	view(`<div class="card"><h2>UBI 卷</h2><p class="sub">0x700000 之后的整个区域是一个 UBI。系统固件在 <span class="mono">fit</span>
		（或 kernel/rootfs）卷，U-Boot 环境变量在 <span class="mono">ubootenv/ubootenv2</span>。</p><div id="ubi_box">正在读取…</div></div>`);
	const load = async () => {
		try {
			const info = await get("/ubi/info", true);
			const vols = (await get("/ubi/volumes", true)).volumes || [];
			$("ubi_box").innerHTML = `<div class="kv" style="margin-bottom:10px"><div>状态</div><div>${info.attached ? '<span class="chip ok">已挂载</span>' : '<span class="chip warn">未挂载</span>'}
				${esc(info.mtd_name || "")}</div></div>
				<table><thead><tr><th>ID</th><th>名称</th><th class="r">大小</th><th>类型</th><th></th></tr></thead><tbody>` +
				vols.map((v) => `<tr><td>${v.id}</td><td class="mono">${esc(v.name)}${v.corrupted ? ' <span class="chip err">损坏</span>' : ""}</td>
				<td class="r">${human(v.size)}</td><td>${esc(v.type)}</td>
				<td class="r"><button class="btn sm" data-r="${esc(v.name)}">删除</button></td></tr>`).join("") +
				`</tbody></table>${vols.length ? "" : '<p class="sub">没有卷。刷入固件时会自动创建。</p>'}`;
			$("ubi_box").querySelectorAll("[data-r]").forEach((b) => b.onclick = async () => {
				const n = b.dataset.r;
				const env = n === "ubootenv" || n === "ubootenv2";
				const sys = n === "fit" || n === "kernel" || n === "rootfs";
				if (!(await confirmBox("删除 UBI 卷 " + n,
					env ? "这是 U-Boot 环境变量卷。删除后变量恢复默认，下次保存时自动重建。" :
					sys ? "这是系统固件卷，删除后系统无法启动，需要重新刷固件。" : "删除后数据无法恢复。",
					"删除", true, sys ? n : null))) return;
				try { await post("/ubi/remove", { name: n }); load(); }
				catch (e) { modal(errorHtml("删除失败：" + e.message, null) + `<div class="row"><button class="btn" onclick="closeModal()">关闭</button></div>`); }
			});
		} catch (e) { $("ubi_box").innerHTML = errorHtml("读取失败：" + e.message, null); }
	};
	load();
};

VIEWS.console = () => {
	view(`<div class="card"><h2>命令行</h2>
		<div class="note err"><b>危险：</b>这里可以直接执行任何 U-Boot 命令。不要对 bl2、fip、factory_info、art 执行
		<span class="mono">mtd erase / mtd write</span>，误操作只能拆机 TTL 修复。</div>
		<div class="term" id="term"></div>
		<div class="row"><input type="text" id="cmd" placeholder="输入命令，回车执行，例如 printenv / mtd list / ubi info" style="flex:1">
		<button class="btn pri" id="run">执行</button><button class="btn" id="clr">清屏</button></div>
		<div class="row hide" id="tok_row"><input type="password" id="tok" placeholder="控制台口令（failsafe_console_token）" style="flex:1"></div></div>`);
	const term = $("term");
	const out = (t) => { term.textContent += t; term.scrollTop = term.scrollHeight; };
	const poll = async () => {
		for (let i = 0; i < 600; i++) {
			let j;
			try { j = await post("/console/poll", $("tok").value ? { token: $("tok").value } : {}, true); }
			catch (e) { out("\n[poll 失败：" + e.message + "]\n"); return; }
			if (j.data) out(j.data);
			if (!j.busy && !j.avail) return;
			await new Promise((r) => setTimeout(r, j.avail ? 50 : 300));
		}
	};
	const run = async () => {
		const c = $("cmd").value.trim();
		if (!c) return;
		$("cmd").value = "";
		try {
			const fields = { cmd: c };
			if ($("tok").value) fields.token = $("tok").value;
			const j = await post("/console/exec", fields, true);
			if (j.error) out("[" + j.error + "]\n");
		} catch (e) {
			if (/forbidden/.test(e.message)) { $("tok_row").classList.remove("hide"); out("[需要控制台口令]\n"); return; }
			out("[执行失败：" + e.message + "]\n");
		}
		poll();
	};
	$("run").onclick = run;
	$("cmd").onkeydown = (e) => { if (e.key === "Enter") run(); };
	$("clr").onclick = async () => { term.textContent = ""; try { await post("/console/clear", {}); } catch (e) { /* ignore */ } };
	poll();
	$("cmd").focus();
};

VIEWS.system = () => {
	view(`<div class="card"><h2>系统操作</h2>
		<div class="row" style="margin-top:0">
		<button class="btn big pri" id="b_boot">尝试启动系统</button>
		<button class="btn big" id="b_reboot">重启设备</button></div>
		<div class="note warn">此预览版不提供“重启并保存恢复模式”功能，因为对应上游接口会写入 UBI 环境变量；系统启动也需要已安装正确的 FIT 卷。</div>
		<p class="sub">目前已验证可在 TTL 命令行执行 <span class="mono">httpd</span> 进入 Web 恢复。Reset / Mesh 上电自动恢复仍需实测。</p></div>
		<div class="card"><h3>关于</h3><div class="kv">
		<div>版本</div><div class="mono">${esc(S.ver)}</div>
		<div>设备</div><div>${esc((S.sys && S.sys.board && S.sys.board.model) || "WMA301 V2")}</div>
		<div>上游</div><div><a href="https://github.com/Yuzhii0718/uboot-airoha-mediatek" target="_blank" rel="noopener">U-Boot 2026.10 · Yuzhii0718</a></div>
		<div>移植</div><div><a href="https://github.com/pzcn/bl-mt798x-dhcpd/tree/feat/wma301-uboot-2026.10" target="_blank" rel="noopener">WMA301 2026.10 experimental</a></div>
		<div>许可证</div><div>GPL-2.0</div></div></div>`);
	$("b_boot").onclick = async () => { if (await confirmBox("尝试启动系统", "仅当 UBI 内已有可启动的 FIT 时才会成功。", "启动")) doBoot("boot"); };
	$("b_reboot").onclick = async () => { if (await confirmBox("重启", "设备将重新启动，不会自动保存环境。", "重启")) doBoot("reboot"); };
};
