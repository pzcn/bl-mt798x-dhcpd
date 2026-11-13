/*
 * WMA301 recovery Web UI (single page) for the U-Boot failsafe httpd of
 * Yuzhii0718/uboot-airoha-mediatek (2026.10). APIs used:
 *   /version /sysinfo /upload /result /last-error /reboot /reboot-failsafe /boot
 *   /backup/info /backup/main
 *   /wma301/health /wma301/fitinfo /wma301/fitcheck /wma301/reset-config
 */
"use strict";

const S = { ver: "", sys: null, health: null, fit: null, route: "", busy: false };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
	(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const human = (n) => n >= 1048576 ? (n / 1048576).toFixed(2) + " MiB" :
	n >= 1024 ? (n / 1024).toFixed(0) + " KiB" : n + " B";
const macText = () => String((S.sys && S.sys.mac) || "").toUpperCase();

const ROUTES = [
	{ id: "firmware", title: "固件" },
	{ id: "initramfs", title: "内存启动" },
	{ id: "uboot", title: "U-Boot 更新" },
	{ id: "backup", title: "备份" },
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
	const out = { code: "", error: "" };
	for (const l of String(text).split("\n")) {
		if (l.indexOf("code:") === 0) out.code = l.slice(5);
		if (l.indexOf("error:") === 0) out.error = l.slice(6);
	}
	return out;
}
async function lastError() {
	try { return await get("/last-error", true); } catch (e) { return { code: 0, error: "" }; }
}

/* ------------------------------------------------- local flags --------- */
/* Browser storage is a convenience only; it may be missing or throw. */
function flagGet(k) { try { return localStorage.getItem("wma301_" + k); } catch (e) { return null; } }
function flagSet(k, v) { try { localStorage.setItem("wma301_" + k, v); } catch (e) { /* ignore */ } }
const backupKey = () => "art_" + (macText().replace(/:/g, "") || "unknown");

/* --------------------------------------------------------- sha-256 ----- */
/* crypto.subtle is unavailable on plain http://192.168.1.1, so hash in JS. */
const SHA_K = new Uint32Array([
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
function sha256(bytes) {
	const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
		0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
	const w = new Uint32Array(64);
	const n = bytes.length, total = ((n + 9 + 63) >> 6) << 6;
	const tail = new Uint8Array(total - (n & ~63));
	tail.set(bytes.subarray(n & ~63));
	tail[n & 63] = 0x80;
	const bits = n * 8, dv = new DataView(tail.buffer);
	dv.setUint32(tail.length - 8, Math.floor(bits / 0x100000000));
	dv.setUint32(tail.length - 4, bits >>> 0);
	const block = (src, off) => {
		for (let i = 0; i < 16; i++)
			w[i] = (src[off + i * 4] << 24) | (src[off + i * 4 + 1] << 16) | (src[off + i * 4 + 2] << 8) | src[off + i * 4 + 3];
		for (let i = 16; i < 64; i++) {
			const a = w[i - 15], b = w[i - 2];
			const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
			const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
			w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
		}
		let [A, B, C, D, E, F, G, H] = h;
		for (let i = 0; i < 64; i++) {
			const S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7));
			const t1 = (H + S1 + ((E & F) ^ (~E & G)) + SHA_K[i] + w[i]) | 0;
			const S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10));
			const t2 = (S0 + ((A & B) ^ (A & C) ^ (B & C))) | 0;
			H = G; G = F; F = E; E = (D + t1) | 0; D = C; C = B; B = A; A = (t1 + t2) | 0;
		}
		h[0] += A; h[1] += B; h[2] += C; h[3] += D; h[4] += E; h[5] += F; h[6] += G; h[7] += H;
	};
	for (let off = 0; off + 64 <= (n & ~63); off += 64) block(bytes, off);
	for (let off = 0; off < tail.length; off += 64) block(tail, off);
	return Array.from(h, (x) => x.toString(16).padStart(8, "0")).join("");
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
	$("nav").innerHTML = ROUTES.map((r) =>
		`<a href="#${r.id}" class="${r.id === S.route ? "on" : ""}">${r.title}</a>`).join("");
}
function renderFoot() {
	$("foot").innerHTML =
		`<div class="mono">${esc(S.ver)}</div>
		<div>底层：<a href="https://github.com/Yuzhii0718/uboot-airoha-mediatek" target="_blank" rel="noopener">Yuzhii0718/uboot-airoha-mediatek</a>
		（MediaTek U-Boot）· WMA301 适配与界面：<a href="https://github.com/pzcn/bl-mt798x-dhcpd/tree/feat/wma301-uboot-2026.10" target="_blank" rel="noopener">pzcn/bl-mt798x-dhcpd</a>
		· GPL-2.0</div>`;
}
function route() {
	if (S.busy) return;
	let id = (location.hash || "#firmware").slice(1);
	if (["flashing", "booting", "fail", "reboot"].indexOf(id) >= 0) id = id === "reboot" ? "system" : "firmware";
	const r = ROUTES.find((x) => x.id === id) || ROUTES[0];
	S.route = r.id;
	renderNav();
	VIEWS[r.id]();
}
function view(html) { $("view").innerHTML = html; }

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

const KIND = {
	firmware: { title: "固件", go: "开始刷入",
		msg: "将写入 UBI 中的 <b>fit</b> 卷，并重建 <b>rootfs_data</b>（系统配置会被清空）。" +
			"bl2、fip、factory_info、art 和 ubootenv/ubootenv2 不会被修改。" },
	initramfs: { title: "内存启动镜像", go: "启动", msg: "将从内存启动镜像，不修改 flash。" },
	fip: { title: "U-Boot 更新包", go: "开始更新", msg: "将更新 FIP 中的 BL33，保留原厂 BL2/BL31。" },
};

async function precheck(file, kind, area) {
	if (!KIND[kind]) { area.innerHTML = errorHtml("不支持该操作", null); return; }
	const type = sniff(await file.slice(0, 512).arrayBuffer());
	const bad = (title, hint) => {
		area.innerHTML = steps(0) + errorHtml(title, { error: hint }) +
			`<div class="row"><button class="btn" onclick="route()">重新选择</button></div>`;
	};
	if (kind === "fip" && type !== "WMA301 BL33 更新包")
		return bad("这不是 WMABL33 更新包", "请选择 WMA301_BL33_UPDATE.bin");
	if (kind === "firmware" && type !== "FIT 镜像（.itb）")
		return bad("这不是 sysupgrade.itb", (type ? "这是 " + type + "。" : "") + "请选择 *-squashfs-sysupgrade.itb");
	runUpload(kind, file, area);
}

async function runUpload(kind, file, area) {
	const k = KIND[kind];
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
		area.innerHTML = steps(1) + `<div class="note ok">上传完成，校验通过。</div>
			<div class="kv"><div>文件</div><div>${esc(file.name)}</div><div>大小</div><div>${human(+parts[0] || file.size)}</div>
			<div>MD5</div><div class="mono">${esc(parts[1] || "")}</div></div>
			<div class="note">${k.msg}</div>
			<div class="row"><button class="btn" id="up_cancel">取消</button>
			<button class="btn big pri" id="up_go">${k.go}</button></div>`;
		const go = await new Promise((res) => { $("up_go").onclick = () => res(true); $("up_cancel").onclick = () => res(false); });
		if (!go) { S.busy = false; route(); return; }
		area.innerHTML = steps(2) + `<h3>${kind === "initramfs" ? "正在准备启动…" : "正在写入" + k.title + "…"}</h3>
			<div class="bar indet"><i></i></div>` +
			(kind === "initramfs" ? "" : `<div class="note warn"><b>写入期间请勿断电</b>，也不要关闭本页面。完成后会自动读回校验。</div>`);
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
		area.innerHTML = steps(4) + `<div class="note ok"><b>${k.title}写入成功，读回校验通过。</b></div>
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

function fmtTime(ts) {
	if (!ts) return "—";
	const d = new Date(ts * 1000);
	return isNaN(d) ? "—" : d.toLocaleString();
}
function fitSummary(f) {
	if (!f) return "正在读取…";
	if (!f.present) return '<span class="chip warn">未安装</span>';
	if (f.error) return `<span class="chip err">${esc(f.error)}</span>`;
	const kernel = (f.images || []).find((i) => i.type === "kernel");
	return `${esc((kernel && kernel.description) || f.config || f.description || "FIT")}
		<div class="hint">${esc(f.config || "")}${f.config ? " · " : ""}编译于 ${esc(fmtTime(f.timestamp))} · ${human(f.volume_bytes || 0)}</div>`;
}
function healthSummary(h) {
	if (!h) return "正在读取…";
	if (!h.ubi) return `<span class="chip err">UBI 未挂载</span>`;
	const u = h.ubi;
	const spare = u.spare_pebs > 2 ? "ok" : u.spare_pebs > 0 ? "warn" : "err";
	return `<span class="chip ${spare}">备用块 ${u.spare_pebs}</span> 坏块 ${h.chip_bad_blocks >= 0 ? h.chip_bad_blocks : "?"}
		<div class="hint">最大擦写 ${u.max_ec} · 平均 ${u.mean_ec}${u.corr_pebs ? " · 待修复 " + u.corr_pebs : ""}</div>`;
}

VIEWS.firmware = () => {
	const sys = S.sys || {};
	const banner = flagGet(backupKey()) ? "" :
		`<div class="note warn"><b>还没有备份过本机的无线校准数据（art）。</b>它丢失后无法恢复，建议先 <a href="#backup">备份全部分区</a>。</div>`;
	view(`${banner}<div class="grid">
		<div class="stat"><div class="k">设备</div><div class="v">${esc((sys.board && sys.board.model) || "WMA301 V2")}</div></div>
		<div class="stat"><div class="k">U-Boot</div><div class="v">${esc((S.ver.match(/U-Boot \S+/) || ["2026.10"])[0])}</div></div>
		<div class="stat"><div class="k">MAC</div><div class="v mono">${esc(macText() || "—")}</div></div>
		<div class="stat"><div class="k">NAND</div><div class="v" id="st_health">${healthSummary(S.health)}</div></div>
		</div>
		<div class="card" style="margin-top:16px"><h2>已安装固件</h2>
		<div id="st_fit">${fitSummary(S.fit)}</div>
		<div class="row"><button class="btn" id="b_check">完整性检查</button><span class="sub" id="chk_txt" style="margin:0"></span></div></div>
		<div class="card"><h2>刷入固件</h2>
		<p class="sub">上传 ImmortalWrt 的 <span class="mono">*-squashfs-sysupgrade.itb</span>。U-Boot 会校验 FIT 结构和适用机型（tplink,wma301-v2），写入后整卷读回比对。</p>
		<div id="fw_area">${steps(0)}${dropZone("fw", ".itb", "仅支持 *-sysupgrade.itb")}</div>
		<div class="row"><a class="btn" href="#initramfs">改为内存启动</a><a class="btn" href="#uboot">更新 U-Boot</a></div></div>`);
	bindDrop("fw", (f) => precheck(f, "firmware", $("fw_area")));
	$("b_check").onclick = fitCheck;
	refreshStatus();
};

async function refreshStatus() {
	try { S.health = await get("/wma301/health", true); } catch (e) { S.health = null; }
	try { S.fit = await get("/wma301/fitinfo", true); } catch (e) { S.fit = { present: true, error: "读取失败" }; }
	if (S.route !== "firmware") return;
	if ($("st_health")) $("st_health").innerHTML = healthSummary(S.health);
	if ($("st_fit")) $("st_fit").innerHTML = fitSummary(S.fit);
}

async function fitCheck() {
	const btn = $("b_check"), txt = $("chk_txt");
	btn.disabled = true; S.busy = true;
	txt.textContent = "正在读取整个 fit 卷并校验哈希，约需 10 秒…";
	try {
		const r = await post("/wma301/fitcheck", {}, true);
		const stage = { read: "NAND 读取出错", format: "不是有效的 FIT", hash: "哈希不匹配", size: "卷过大" };
		txt.innerHTML = !r.present ? '<span class="chip warn">没有已安装的固件</span>' :
			r.ok ? `<span class="chip ok">完整</span> 已读取 ${human(r.bytes)}，所有镜像哈希正确` :
			`<span class="chip err">${esc(stage[r.stage] || "失败")}</span> ${esc(r.error || "")}，建议重新刷入固件`;
	} catch (e) {
		txt.textContent = "检查失败：" + e.message;
	}
	btn.disabled = false; S.busy = false;
}

VIEWS.initramfs = () => {
	view(`<div class="card"><h2>内存启动</h2>
		<p class="sub">上传 initramfs / recovery 镜像（例如 <span class="mono">*-initramfs-recovery.itb</span>），
		设备直接从内存运行它，<b>不写 flash</b>。适合测试新固件或救急。</p>
		<div id="ir_area">${steps(0)}${dropZone("ir", ".itb,.bin", "通常是 *-initramfs-recovery.itb")}</div></div>`);
	bindDrop("ir", (f) => precheck(f, "initramfs", $("ir_area")));
};

VIEWS.uboot = () => {
	view(`<div class="card"><h2>U-Boot 更新</h2>
		<p class="sub">上传 <span class="mono">WMA301_BL33_UPDATE.bin</span>，自动校验板型、SHA-256、加载地址和 FIP 布局，只更新 BL33，保留原厂 BL2/BL31。</p>
		<div class="note">仅适用于已刷入自定义 U-Boot 的设备；原厂设备首次安装请使用工具箱或 TTL。</div>
		<div id="ub_area">${steps(0)}${dropZone("ub", ".bin", "仅支持 WMA301_BL33_UPDATE.bin")}</div>
		<p class="sub" style="margin-top:12px">当前：<span class="mono">${esc(S.ver)}</span></p></div>`);
	bindDrop("ub", (file) => precheck(file, "fip", $("ub_area")));
};

VIEWS.backup = async () => {
	view(`<div class="card"><h2>备份</h2>
		<p class="sub">只读备份 bl2、fip、reserved、factory_info、art、config 分区。</p>
		<div class="note warn"><b>art</b> 是本机的无线校准数据，<b>factory_info</b> 含 MAC 等出厂信息，丢失后无法恢复，请务必妥善保存。</div>
		<div class="row" style="margin-top:0"><button class="btn big pri" id="bk_all" disabled>备份全部分区</button><span class="sub" id="bk_all_s" style="margin:0"></span></div>
		<div id="bk_list" style="margin-top:14px">正在读取分区表…</div></div>`);
	try {
		const info = await get("/backup/info", true);
		const parts = (info.mtd && info.mtd.parts) || [];
		const mac = (macText() || "wma301").replace(/:/g, "");
		$("bk_list").innerHTML = `<table><thead><tr><th>分区</th><th class="r">大小</th><th></th></tr></thead><tbody>` +
			parts.map((p, i) => `<tr><td>${esc(p.name)}
				${p.name === "art" || p.name === "factory_info" ? '<span class="chip warn">重要</span>' : ""}
				<div class="hint mono" id="bk_h${i}"></div></td>
				<td class="r">${human(p.size)}</td><td class="r"><button class="btn sm" data-i="${i}">下载</button>
				<span class="sub" id="bk_s${i}"></span></td></tr>`).join("") + `</tbody></table>`;
		const one = (i) => downloadPart(parts[i], mac, i);
		$("bk_list").querySelectorAll("button[data-i]").forEach((b) => { b.onclick = () => one(+b.dataset.i); });
		$("bk_all").disabled = !parts.length;
		$("bk_all").onclick = async () => {
			$("bk_all").disabled = true;
			let ok = 0;
			for (let i = 0; i < parts.length; i++) {
				$("bk_all_s").textContent = `正在备份 ${parts[i].name}（${i + 1}/${parts.length}）`;
				if (await one(i)) ok++;
			}
			$("bk_all_s").textContent = ok === parts.length ? `✓ 已保存 ${ok} 个文件` : `完成 ${ok}/${parts.length}，失败的请单独重试`;
			$("bk_all").disabled = false;
		};
	} catch (e) {
		$("bk_list").innerHTML = errorHtml("读取分区表失败：" + e.message, null);
	}
};

async function downloadPart(p, mac, i) {
	const btn = document.querySelector(`button[data-i="${i}"]`), status = $("bk_s" + i);
	if (btn) btn.disabled = true;
	try {
		const fd = new FormData();
		fd.append("mode", "part"); fd.append("storage", "mtd"); fd.append("target", p.name);
		const r = await fetch("/backup/main", { method: "POST", body: fd });
		if (!r.ok) throw new Error("HTTP " + r.status);
		const reader = r.body.getReader();
		const data = new Uint8Array(p.size); let got = 0;
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			if (got + value.length > p.size) throw new Error("数据超长");
			data.set(value, got); got += value.length;
			status.textContent = (got / p.size * 100).toFixed(0) + "%";
		}
		if (got !== p.size) throw new Error("长度不对：" + got + " / " + p.size);
		status.textContent = "计算 SHA-256…";
		await new Promise((r2) => setTimeout(r2, 0));
		const digest = sha256(data);
		const a = document.createElement("a");
		a.href = URL.createObjectURL(new Blob([data], { type: "application/octet-stream" }));
		a.download = `${mac}_${p.name}.bin`;
		document.body.appendChild(a); a.click(); a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 10000);
		$("bk_h" + i).textContent = "SHA-256 " + digest;
		status.textContent = "✓ 已保存";
		if (p.name === "art") flagSet(backupKey(), digest);
		if (btn) btn.disabled = false;
		return true;
	} catch (e) {
		status.textContent = "失败：" + e.message;
		if (btn) btn.disabled = false;
		return false;
	}
}

VIEWS.system = () => {
	view(`<div class="card"><h2>系统操作</h2>
		<div class="row" style="margin-top:0">
		<button class="btn big pri" id="b_boot">启动系统</button>
		<button class="btn big" id="b_reboot">重启设备</button>
		<button class="btn big" id="b_failsafe">重启并进入恢复模式</button></div>
		<p class="sub" style="margin-top:12px">不接 TTL 也能进入恢复模式：上电时按住 Reset 或 Mesh 约 6 秒；
		或者在 ImmortalWrt 中执行 <span class="mono">reboot-recovery</span>。</p></div>
		<div class="card"><h2>清除系统配置</h2>
		<p class="sub">忘记 ImmortalWrt 密码或配置出错时使用：只删除并重建 <span class="mono">rootfs_data</span> 卷，
		等同于在系统里恢复出厂设置。固件、U-Boot、MAC 和无线校准数据都不会改动。</p>
		<div class="row" style="margin-top:0"><button class="btn dng" id="b_reset">清除系统配置</button><span class="sub" id="reset_txt" style="margin:0"></span></div></div>
		<div class="card"><h3>关于</h3><div class="kv">
		<div>版本</div><div class="mono">${esc(S.ver)}</div>
		<div>设备</div><div>${esc((S.sys && S.sys.board && S.sys.board.model) || "WMA301 V2")}</div>
		<div>上游</div><div><a href="https://github.com/Yuzhii0718/uboot-airoha-mediatek" target="_blank" rel="noopener">U-Boot 2026.10 · Yuzhii0718</a></div>
		<div>移植</div><div><a href="https://github.com/pzcn/bl-mt798x-dhcpd/tree/feat/wma301-uboot-2026.10" target="_blank" rel="noopener">WMA301 2026.10</a></div>
		<div>许可证</div><div>GPL-2.0</div></div></div>`);
	$("b_boot").onclick = async () => { if (await confirmBox("启动系统", "仅当 UBI 内已有可启动的固件时才会成功。", "启动")) doBoot("boot"); };
	$("b_reboot").onclick = async () => { if (await confirmBox("重启", "设备将重新启动。", "重启")) doBoot("reboot"); };
	$("b_failsafe").onclick = async () => {
		if (await confirmBox("重启并进入恢复模式", "设备重启后会直接回到本页面，下一次重启恢复正常启动。", "重启")) doBoot("failsafe");
	};
	$("b_reset").onclick = async () => {
		if (!(await confirmBox("清除系统配置",
			"ImmortalWrt 的所有设置（密码、网络、无线、已安装的软件包）都会被清除，下次启动时恢复默认。",
			"清除", true, "RESET"))) return;
		$("b_reset").disabled = true;
		$("reset_txt").textContent = "正在清除…";
		try {
			await post("/wma301/reset-config", { confirm: "RESET" });
			$("reset_txt").innerHTML = '<span class="chip ok">已清除</span> 启动系统后即为默认配置';
		} catch (e) {
			$("reset_txt").textContent = "失败：" + e.message;
		}
		$("b_reset").disabled = false;
	};
};

boot();
