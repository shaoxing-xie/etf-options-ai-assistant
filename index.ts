import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { execFile } from "child_process";
import { promisify } from "util";
import { existsSync, readFileSync } from "fs";
import { join } from "path";

const execFileAsync = promisify(execFile);

const HOME = process.env.HOME || "";

function getDefaultScriptPath(): string {
  return HOME ? `${HOME}/etf-options-ai-assistant/tool_runner.py` : "";
}

function getManifestPath(): string {
  const candidates = [
    join(__dirname, "config", "tools_manifest.json"),
    join(process.cwd(), "config", "tools_manifest.json"),
  ];
  for (const p of candidates) {
    if (existsSync(p)) return p;
  }
  return candidates[0];
}

function loadToolsManifest(): { tools: Array<{ id: string; label: string; description: string; parameters: object }> } {
  const manifestPath = process.env.OPTION_TRADING_ASSISTANT_MANIFEST_PATH || getManifestPath();
  try {
    const raw = readFileSync(manifestPath, "utf-8");
    const data = JSON.parse(raw) as { tools?: Array<{ id: string; label: string; description: string; parameters?: object }> };
    return { tools: data.tools || [] };
  } catch (e) {
    throw new Error(`加载工具清单失败 (${manifestPath}): ${e}`);
  }
}

const defaultPythonBin = (() => {
  if (HOME) {
    const projectVenvPython = `${HOME}/etf-options-ai-assistant/.venv/bin/python`;
    if (existsSync(projectVenvPython)) return projectVenvPython;
    const envPython = process.env.OPTION_TRADING_ASSISTANT_PYTHON;
    if (envPython?.trim()) return envPython;
    const pipxMootdxPython = `${HOME}/.local/share/pipx/venvs/mootdx/bin/python`;
    if (existsSync(pipxMootdxPython)) return pipxMootdxPython;
  }
  return "python3";
})();

const PYTHON_BIN = defaultPythonBin;

const plugin = {
  id: "option-trading-assistant",
  name: "Option Trading Assistant",
  description: "期权交易助手插件 - 数据采集、分析、通知、研究、涨停回马枪与回测工具",
  configSchema: {
    type: "object",
    properties: {
      apiBaseUrl: {
        type: "string",
        default: "http://localhost:5000",
        description: "原系统API基础地址",
      },
      apiKey: { type: "string", description: "API Key（可选）" },
      scriptPath: {
        type: "string",
        description: "tool_runner.py 绝对路径，不填则用默认（HOME/etf-options-ai-assistant/tool_runner.py）或环境变量 OPTION_TRADING_ASSISTANT_SCRIPT_PATH",
      },
      manifestPath: {
        type: "string",
        description: "工具清单 JSON 路径（可选），不填则用 config/tools_manifest.json",
      },
      toolExecTimeoutMs: {
        type: "number",
        default: 1_200_000,
        description:
          "tool_runner.py 子进程超时（毫秒）。盘后分析 + overlay + 日报发送常超过 60s；与 cron timeoutSeconds≈1200 对齐，默认 20 分钟。",
      },
    },
  },
  register(api: OpenClawPluginApi) {
    registerAllTools(api);
    api.logger.info?.("option-trading-assistant: Registered all tools from manifest");
  },
};

function registerAllTools(api: OpenClawPluginApi) {
  const config = (api as { getConfig?: () => Record<string, unknown> }).getConfig?.() ?? {};
  const scriptPath =
    (process.env.OPTION_TRADING_ASSISTANT_SCRIPT_PATH as string) ||
    (config.scriptPath as string) ||
    getDefaultScriptPath();

  if (config.manifestPath) {
    process.env.OPTION_TRADING_ASSISTANT_MANIFEST_PATH = config.manifestPath as string;
  }

  const { tools } = loadToolsManifest();
  const toolExecTimeoutMsRaw = config.toolExecTimeoutMs;
  const toolExecTimeoutMs =
    typeof toolExecTimeoutMsRaw === "number" && Number.isFinite(toolExecTimeoutMsRaw) && toolExecTimeoutMsRaw >= 5_000
      ? Math.floor(toolExecTimeoutMsRaw)
      : 1_200_000;

  for (const t of tools) {
    const id = t.id;
    const parameters = (t.parameters && typeof t.parameters === "object" && "type" in t.parameters)
      ? (t.parameters as { type: string; properties?: Record<string, unknown>; required?: string[] })
      : { type: "object" as const, properties: {} };
  
  api.registerTool(
    {
        name: id,
        label: t.label || id,
        description: t.description || "",
      parameters: {
          type: parameters.type || "object",
          properties: parameters.properties || {},
          ...(Array.isArray(parameters.required) && parameters.required.length > 0 ? { required: parameters.required } : {}),
      },
      async execute(_toolCallId, params) {
          return await callPythonTool(scriptPath, id, params ?? {}, toolExecTimeoutMs);
        },
      },
      { name: id }
    );
  }
}

async function callPythonTool(
  scriptPath: string,
  toolName: string,
  params: Record<string, unknown>,
  timeoutMs: number,
) {
  try {
    const argsJson = JSON.stringify(params || {});
    const { stdout, stderr } = await execFileAsync(PYTHON_BIN, [scriptPath, toolName, argsJson], {
        timeout: timeoutMs,
        maxBuffer: 10 * 1024 * 1024,
    });

    if (stderr && !stdout) {
      return { content: [{ type: "text" as const, text: `错误: ${stderr}` }] };
    }

    try {
      const result = JSON.parse(stdout);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
        details: result,
      };
    } catch {
      return { content: [{ type: "text" as const, text: stdout }] };
    }
  } catch (err) {
    const errorObj = err as { message?: string; code?: number | string } | Error;
    const errorMsg =
      errorObj instanceof Error
        ? errorObj.message
        : typeof (errorObj as { message?: string }).message === "string"
          ? (errorObj as { message: string }).message
        : String(errorObj);
    const exitCode =
      typeof (errorObj as { code?: number | string }).code !== "undefined"
        ? (errorObj as { code: number | string }).code
        : undefined;
    return {
      content: [{ type: "text" as const, text: `执行失败: ${errorMsg}` }],
      details: { error: errorMsg, exitCode },
    };
  }
}

export default plugin;
