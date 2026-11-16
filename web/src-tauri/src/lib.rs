use std::env;
use std::fs::File;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::utils::assets::AssetKey;
use tauri::{WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// CREATE_NO_WINDOW：拉起子进程时不要给它分配控制台（否则会闪黑窗）
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 后端固定端口：前端据此跨源访问（注入 window.__ALTUM_API__）
const BACKEND_PORT: u16 = 8765;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);

/// python.exe → pythonw.exe（同目录）。
/// pythonw 没有控制台，Windows 上不会弹出黑色命令行窗口。
fn console_free(exe: &str) -> String {
    if exe.to_ascii_lowercase().ends_with("python.exe") {
        let stem = &exe[..exe.len() - "python.exe".len()];
        let w = format!("{stem}pythonw.exe");
        if Path::new(&w).is_file() {
            return w;
        }
    }
    exe.to_string()
}

/// 找 python 解释器：环境变量 → PATH（逐目录找，不再 spawn `where.exe`，
/// 那是控制台程序，会闪一个黑窗）→ 常见安装位置。
/// 统一转成 pythonw.exe（无控制台）。
fn python_exe() -> String {
    if let Ok(p) = env::var("ALTUM_PYTHON") {
        if Path::new(&p).is_file() {
            return console_free(&p);
        }
    }
    if let Ok(path) = env::var("PATH") {
        for dir in path.split(';') {
            let dir = dir.trim();
            if dir.is_empty() || dir.contains("WindowsApps") {
                continue;
            }
            for name in ["pythonw.exe", "python.exe"] {
                let cand = Path::new(dir).join(name);
                if cand.is_file() {
                    return console_free(&cand.to_string_lossy());
                }
            }
        }
    }
    for candidate in [
        r"C:\Users\admin\AppData\Local\Programs\Python\Python312\pythonw.exe",
        r"C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe",
        r"C:\Python312\pythonw.exe",
        r"C:\Python312\python.exe",
    ] {
        if Path::new(candidate).is_file() {
            return candidate.to_string();
        }
    }
    "python".to_string()
}

/// 找后端代码目录（含 server.py）
fn find_backend_dir() -> Option<PathBuf> {
    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            // 1) 真正的项目根（含 api/ 与 web/src）：开发态 target/release 向上四级就是它。
            //    优先用它，参数配置与浏览器版保持同一份。
            //    ⚠️ 不能只看 api/：tauri build 会把 resources 平铺到 target/release/，
            //    那里也有 api/ 与配置文件，但不是项目根。
            let mut cur = dir.to_path_buf();
            for _ in 0..8 {
                if cur.join("api").join("paths.py").is_file()
                    && cur.join("web").join("src").is_dir()
                    && cur.join("altium_tools_config.json").is_file()
                {
                    return Some(cur);
                }
                match cur.parent() {
                    Some(p) => cur = p.to_path_buf(),
                    None => break,
                }
            }
            // 2) 安装态：exe 同级 resources/（后端代码副本）
            let res = dir.join("resources");
            if res.join("server.py").is_file() {
                return Some(res);
            }
            if dir.join("server.py").is_file() {
                return Some(dir.to_path_buf());
            }
        }
    }
    // 3) 从当前目录逐级向上找
    let mut cur = env::current_dir().ok()?;
    for _ in 0..8 {
        if cur.join("server.py").is_file() {
            return Some(cur);
        }
        cur = cur.parent()?.to_path_buf();
    }
    None
}

/// 探活：发一个 HTTP GET /api/health，看返回里有没有 "ok"
fn probe(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(500)) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let req = "GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n";
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = String::new();
    let _ = stream.read_to_string(&mut buf);
    buf.contains("\"ok\"")
}

fn wait_health(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if probe(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

/// 彻底结束 Python 进程树（Windows 上 taskkill /T 会连子进程一起收）
fn kill_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        let pid = child.id();
        let mut cmd = Command::new("taskkill");
        cmd.args(["/T", "/F", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW); // 别给它弹控制台
        let _ = cmd.status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

pub fn run() {
    let backend_dir = find_backend_dir();
    let child_slot: Arc<Mutex<Option<Child>>> = Arc::new(Mutex::new(None));
    let slot_for_setup = child_slot.clone();

    let context = tauri::generate_context!();
    if !cfg!(debug_assertions) && context.assets.get(&AssetKey::from("index.html")).is_none() {
        eprintln!(
            "[altium-tools] 前端资源没有嵌入二进制。\n\
             请改用 `npm run tauri:build` 构建（直接 cargo build 不会嵌入前端资源）。"
        );
    }

    tauri::Builder::default()
        .setup(move |app| {
            let dir = backend_dir
                .clone()
                .or_else(|| env::current_dir().ok())
                .unwrap_or_else(|| PathBuf::from("."));

            // 端口上已经有健康的实例 → 直接复用，不再重复拉起
            let need_spawn = !probe(BACKEND_PORT);
            if need_spawn {
                let python = python_exe();
                let mut cmd = Command::new(python);
                cmd.arg("server.py")
                    .arg("--no-browser")
                    .arg("--port")
                    .arg(BACKEND_PORT.to_string())
                    .arg("--strict-port")
                    .current_dir(&dir)
                    // 让后端把配置/前端产物指到真正的项目目录（桌面版与浏览器版同源）
                    .env("ALTUM_HOME", &dir)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                #[cfg(windows)]
                cmd.creation_flags(CREATE_NO_WINDOW);
                // pythonw 没有控制台，输出无处可去 → 写进临时日志文件，便于排查
                let log_path = env::temp_dir().join("altium_backend.log");
                if let Ok(f) = File::create(&log_path) {
                    if let Ok(f2) = f.try_clone() {
                        cmd.stdout(Stdio::from(f)).stderr(Stdio::from(f2));
                    }
                }
                match cmd.spawn() {
                    Ok(child) => {
                        if let Ok(mut guard) = slot_for_setup.lock() {
                            *guard = Some(child);
                        }
                    }
                    Err(err) => {
                        eprintln!("[altium-tools] 无法启动 Python 后端: {err}");
                    }
                }
            }

            if !wait_health(BACKEND_PORT, HEALTH_TIMEOUT) {
                eprintln!(
                    "[altium-tools] 后端 {BACKEND_PORT} 端口未就绪，前端功能可能不可用"
                );
            }

            let base = format!("http://127.0.0.1:{BACKEND_PORT}");
            let script = format!("window.__ALTUM_API__ = '{base}';");

            let url = if cfg!(debug_assertions) {
                // dev：走 vite dev server
                WebviewUrl::External("http://localhost:5173".parse().unwrap())
            } else {
                // release：走打包进 exe 的前端资源（tauri://localhost/index.html）
                WebviewUrl::App("index.html".into())
            };

            WebviewWindowBuilder::new(app, "main", url)
                .title("Altium 工具集")
                .inner_size(1320.0, 840.0)
                .min_inner_size(1000.0, 660.0)
                .resizable(true)
                .center()
                .initialization_script(script.as_str())
                .build()?;

            Ok(())
        })
        .build(context)
        .expect("Tauri 应用初始化失败")
        .run(move |_handle, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Ok(mut guard) = child_slot.lock() {
                    if let Some(mut child) = guard.take() {
                        kill_tree(&mut child);
                    }
                }
            }
        });
}
