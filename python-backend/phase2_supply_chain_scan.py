#!/usr/bin/env python3
"""
Phase 2 - P2-4: 供应链安全扫描

扫描Python依赖的安全漏洞。
对应OWASP LLM03: Supply Chain Vulnerabilities
"""

import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class VulnerabilityInfo:
    """漏洞信息"""
    package: str
    installed_version: str
    vulnerability_id: str
    severity: str
    description: str
    fixed_version: Optional[str] = None


class SupplyChainScanner:
    """供应链安全扫描器"""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.requirements_path = project_path / "requirements.txt"
        self.vulnerabilities: List[VulnerabilityInfo] = []
        self.scan_results: Dict[str, Any] = {}

    def check_pip_audit_available(self) -> bool:
        """检查pip-audit是否可用"""
        try:
            result = subprocess.run(
                ["pip", "show", "pip-audit"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def install_pip_audit(self) -> bool:
        """安装pip-audit"""
        try:
            result = subprocess.run(
                ["pip", "install", "pip-audit"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def run_pip_audit(self) -> Dict[str, Any]:
        """运行pip-audit扫描"""
        print("  [1/4] 运行pip-audit漏洞扫描...")

        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json", "-r", str(self.requirements_path)],
                capture_output=True,
                text=True,
                cwd=str(self.project_path)
            )

            if result.returncode == 0 and not result.stdout.strip():
                return {"status": "clean", "vulnerabilities": []}

            try:
                audit_result = json.loads(result.stdout) if result.stdout else []
                return {"status": "found" if audit_result else "clean", "vulnerabilities": audit_result}
            except json.JSONDecodeError:
                return {"status": "error", "error": result.stderr or result.stdout}

        except FileNotFoundError:
            return {"status": "error", "error": "pip-audit not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def check_safety_available(self) -> bool:
        """检查safety是否可用"""
        try:
            result = subprocess.run(
                ["pip", "show", "safety"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False

    def run_safety_check(self) -> Dict[str, Any]:
        """运行safety check扫描"""
        print("  [2/4] 运行safety漏洞扫描...")

        try:
            result = subprocess.run(
                ["safety", "check", "--json", "-r", str(self.requirements_path)],
                capture_output=True,
                text=True,
                cwd=str(self.project_path)
            )

            try:
                # safety returns non-zero if vulnerabilities found
                safety_result = json.loads(result.stdout) if result.stdout else {}
                vulns = safety_result.get("vulnerabilities", [])
                return {"status": "found" if vulns else "clean", "vulnerabilities": vulns}
            except json.JSONDecodeError:
                # Try parsing as text output
                if "No known security vulnerabilities found" in result.stdout:
                    return {"status": "clean", "vulnerabilities": []}
                return {"status": "error", "error": result.stderr or result.stdout}

        except FileNotFoundError:
            return {"status": "skipped", "error": "safety not installed"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def analyze_requirements(self) -> Dict[str, Any]:
        """分析requirements.txt"""
        print("  [3/4] 分析依赖项...")

        if not self.requirements_path.exists():
            return {"status": "error", "error": "requirements.txt not found"}

        packages = []
        with open(self.requirements_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Parse package name and version
                    if '==' in line:
                        name, version = line.split('==', 1)
                        packages.append({"name": name.strip(), "version": version.strip(), "pinned": True})
                    elif '>=' in line:
                        name, version = line.split('>=', 1)
                        packages.append({"name": name.strip(), "min_version": version.strip(), "pinned": False})
                    else:
                        packages.append({"name": line.strip(), "version": "unpinned", "pinned": False})

        # Identify high-risk packages
        high_risk_packages = [
            "openai",  # API client - potential for prompt injection
            "httpx",   # HTTP client - SSRF risk
            "pydantic",  # Data validation - deserialization
            "uvicorn",  # Web server - security configs
            "fastapi",  # Web framework - input validation
        ]

        risk_analysis = []
        for pkg in packages:
            if pkg["name"].lower() in high_risk_packages:
                risk_analysis.append({
                    "package": pkg["name"],
                    "risk_type": "high_risk_dependency",
                    "note": "This package handles sensitive operations"
                })
            if not pkg.get("pinned", False):
                risk_analysis.append({
                    "package": pkg["name"],
                    "risk_type": "unpinned_version",
                    "note": "Version not pinned - supply chain risk"
                })

        return {
            "status": "analyzed",
            "total_packages": len(packages),
            "pinned_packages": sum(1 for p in packages if p.get("pinned", False)),
            "unpinned_packages": sum(1 for p in packages if not p.get("pinned", False)),
            "packages": packages,
            "risk_analysis": risk_analysis
        }

    def check_model_provider_security(self) -> Dict[str, Any]:
        """检查模型提供商安全配置"""
        print("  [4/4] 检查模型提供商配置...")

        findings = []

        # Check for hardcoded API keys
        env_path = self.project_path / ".env"
        if env_path.exists():
            with open(env_path, 'r') as f:
                content = f.read()
                if "OPENAI_API_KEY" in content and "sk-" in content:
                    # Check if it's a real key (starts with sk-)
                    if "sk-proj-" in content or "sk-ant-" in content:
                        findings.append({
                            "type": "exposed_api_key",
                            "severity": "critical",
                            "location": ".env",
                            "note": "API key appears to be hardcoded in .env file"
                        })

        # Check for insecure base URL configurations
        server_path = self.project_path / "server.py"
        if server_path.exists():
            with open(server_path, 'r') as f:
                content = f.read()
                if "http://" in content and "localhost" not in content.lower():
                    findings.append({
                        "type": "insecure_url",
                        "severity": "medium",
                        "location": "server.py",
                        "note": "HTTP (non-HTTPS) URL found in server configuration"
                    })

        # Check guardrails configuration
        guardrails_path = self.project_path / "airline" / "guardrails.py"
        if guardrails_path.exists():
            with open(guardrails_path, 'r') as f:
                content = f.read()
                if "disabled" in content.lower() or "bypass" in content.lower():
                    findings.append({
                        "type": "guardrail_concern",
                        "severity": "high",
                        "location": "airline/guardrails.py",
                        "note": "Potential guardrail disable/bypass code found"
                    })

        return {
            "status": "analyzed",
            "findings": findings,
            "model_provider": "OpenAI API (via Moonshot/Kimi)",
            "security_notes": [
                "Model API calls are made to third-party provider",
                "API key management should follow security best practices",
                "Consider implementing request signing and rate limiting"
            ]
        }

    def run_full_scan(self) -> Dict[str, Any]:
        """运行完整的供应链安全扫描"""
        print("\n" + "=" * 70)
        print("   PHASE 2 - P2-4: 供应链安全扫描 (OWASP LLM03)")
        print("=" * 70)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"项目路径: {self.project_path}")
        print()

        # Check and install pip-audit if needed
        if not self.check_pip_audit_available():
            print("  [0/4] 安装pip-audit...")
            self.install_pip_audit()

        # Run all scans
        pip_audit_result = self.run_pip_audit()
        safety_result = self.run_safety_check()
        requirements_analysis = self.analyze_requirements()
        model_security = self.check_model_provider_security()

        # Compile results
        total_vulns = 0
        critical_vulns = 0
        high_vulns = 0

        # Count pip-audit vulnerabilities
        if pip_audit_result.get("status") == "found":
            for vuln in pip_audit_result.get("vulnerabilities", []):
                total_vulns += 1
                # pip-audit doesn't always include severity
                if isinstance(vuln, dict):
                    if vuln.get("severity", "").lower() == "critical":
                        critical_vulns += 1
                    elif vuln.get("severity", "").lower() == "high":
                        high_vulns += 1

        # Count safety vulnerabilities
        if safety_result.get("status") == "found":
            for vuln in safety_result.get("vulnerabilities", []):
                total_vulns += 1

        # Count model security findings
        for finding in model_security.get("findings", []):
            if finding.get("severity") == "critical":
                critical_vulns += 1
            elif finding.get("severity") == "high":
                high_vulns += 1

        # Count unpinned packages as medium risk
        unpinned = requirements_analysis.get("unpinned_packages", 0)

        self.scan_results = {
            "timestamp": datetime.now().isoformat(),
            "test_type": "supply_chain_security",
            "phase": "P2-4",
            "owasp_mapping": "LLM03: Supply Chain Vulnerabilities",
            "summary": {
                "total_vulnerabilities": total_vulns,
                "critical": critical_vulns,
                "high": high_vulns,
                "unpinned_packages": unpinned,
                "overall_risk": "high" if critical_vulns > 0 else ("medium" if high_vulns > 0 or unpinned > 5 else "low")
            },
            "pip_audit": pip_audit_result,
            "safety_check": safety_result,
            "requirements_analysis": requirements_analysis,
            "model_provider_security": model_security,
        }

        return self.scan_results

    def print_summary(self, report: Dict[str, Any]):
        """打印扫描总结"""
        summary = report.get("summary", {})

        print("\n" + "=" * 70)
        print("   供应链安全扫描结果")
        print("=" * 70)
        print(f"""
总漏洞数: {summary.get('total_vulnerabilities', 0)}
  严重(Critical): {summary.get('critical', 0)}
  高危(High): {summary.get('high', 0)}
未固定版本包: {summary.get('unpinned_packages', 0)}
整体风险等级: {summary.get('overall_risk', 'unknown').upper()}
""")

        # pip-audit results
        pip_audit = report.get("pip_audit", {})
        if pip_audit.get("status") == "found":
            print("[!] pip-audit发现的漏洞:")
            for vuln in pip_audit.get("vulnerabilities", [])[:5]:
                if isinstance(vuln, dict):
                    print(f"  - {vuln.get('name', 'unknown')}: {vuln.get('id', 'N/A')}")
        elif pip_audit.get("status") == "clean":
            print("[✓] pip-audit: 未发现已知漏洞")
        else:
            print(f"[!] pip-audit: {pip_audit.get('error', 'unknown error')}")

        # Model security findings
        model_sec = report.get("model_provider_security", {})
        if model_sec.get("findings"):
            print("\n[!] 模型提供商安全发现:")
            for finding in model_sec.get("findings", []):
                print(f"  - [{finding.get('severity', 'unknown').upper()}] {finding.get('type')}")
                print(f"    {finding.get('note')}")
        else:
            print("\n[✓] 模型提供商配置: 未发现明显安全问题")

        # Requirements analysis
        req_analysis = report.get("requirements_analysis", {})
        print(f"\n依赖分析:")
        print(f"  总包数: {req_analysis.get('total_packages', 0)}")
        print(f"  已固定版本: {req_analysis.get('pinned_packages', 0)}")
        print(f"  未固定版本: {req_analysis.get('unpinned_packages', 0)}")

        if req_analysis.get("risk_analysis"):
            print("\n[!] 风险依赖:")
            for risk in req_analysis.get("risk_analysis", [])[:5]:
                print(f"  - {risk.get('package')}: {risk.get('risk_type')}")

        print("\n" + "=" * 70)


def main():
    """主函数"""
    project_path = Path(__file__).parent

    scanner = SupplyChainScanner(project_path)
    report = scanner.run_full_scan()
    scanner.print_summary(report)

    # 保存报告
    output_path = project_path / "testing" / "reports" / f"p2_supply_chain_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n报告已保存: {output_path}")

    return report


if __name__ == "__main__":
    main()
