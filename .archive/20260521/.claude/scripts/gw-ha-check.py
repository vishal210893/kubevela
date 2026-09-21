#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///

"""
Java Spring Boot HA Configuration Checker

Analyzes Java source files to verify high availability best practices:
- Retry annotations (@Retryable, @Retry)
- Circuit breaker patterns (@CircuitBreaker, @HystrixCommand)
- Exponential backoff configuration
- Resilience4j annotations
- Spring Retry configuration
- Connection pool settings
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class Finding:
    """Represents an HA check finding"""
    severity: str  # 'error', 'warning', 'info'
    category: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    recommendation: Optional[str] = None


class JavaHAChecker:
    """Checks Java files for HA patterns"""

    # Annotations to look for
    RETRY_ANNOTATIONS = [
        r'@Retryable',
        r'@Retry',
        r'@CircuitBreaker',
        r'@Bulkhead',
        r'@RateLimiter',
        r'@TimeLimiter',
        r'@HystrixCommand',
    ]

    # Configuration patterns
    BACKOFF_PATTERNS = [
        r'@Backoff\s*\(',
        r'backoff\s*=',
        r'maxDelay\s*=',
        r'delay\s*=',
        r'multiplier\s*=',
    ]

    HIKARI_CONFIG_PATTERNS = [
        r'max-lifetime\s*[:=]',
        r'maxLifetime\s*[:=]',
        r'connection-timeout\s*[:=]',
        r'connectionTimeout\s*[:=]',
    ]

    DNS_TTL_PATTERNS = [
        r'networkaddress\.cache\.ttl',
        r'Security\.setProperty.*ttl',
    ]

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.findings: List[Finding] = []

    def check_all(self) -> List[Finding]:
        """Run all checks and return findings"""
        self.findings = []

        # Find all Java files
        java_files = list(self.base_path.rglob("*.java"))

        if not java_files:
            self.findings.append(Finding(
                severity='info',
                category='discovery',
                message=f'No Java files found in {self.base_path}'
            ))
            return self.findings

        # Check each Java file
        for java_file in java_files:
            self._check_java_file(java_file)

        # Check for application.yml/properties files
        self._check_application_config()

        # Generate summary
        self._generate_summary(java_files)

        return self.findings

    def _check_java_file(self, file_path: Path) -> None:
        """Check a single Java file for HA patterns"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')

            # Check for service/controller annotations (these should have retry logic)
            is_service = re.search(r'@(RestController|Controller|Service|Component)', content) is not None

            if is_service:
                self._check_retry_annotations(file_path, content, lines)
                self._check_hikari_config(file_path, content, lines)
                self._check_dns_ttl_config(file_path, content, lines)

        except Exception as e:
            self.findings.append(Finding(
                severity='warning',
                category='error',
                message=f'Error reading {file_path.name}: {str(e)}',
                file_path=str(file_path)
            ))

    def _check_retry_annotations(self, file_path: Path, content: str, lines: List[str]) -> None:
        """Check for retry annotations and configuration"""
        # Check if file has external dependencies (DB, HTTP calls)
        has_external_deps = any([
            re.search(r'@Autowired.*Repository', content) is not None,
            re.search(r'RestTemplate|WebClient|FeignClient', content) is not None,
            re.search(r'@Query', content) is not None,
            re.search(r'JdbcTemplate|EntityManager', content) is not None,
        ])

        if not has_external_deps:
            return  # No external deps, no retry needed

        # Look for retry annotations
        has_retry = any(
            re.search(pattern, content, re.IGNORECASE) is not None
            for pattern in self.RETRY_ANNOTATIONS
        )

        if not has_retry:
            self.findings.append(Finding(
                severity='error',
                category='retry',
                message=f'Service {file_path.name} makes external calls but lacks retry annotations',
                file_path=str(file_path),
                recommendation='''Add retry annotations to all methods making external calls (database, HTTP, messaging):

Example with spring-retry:
@Retryable(
    value = {SQLException.class, DataAccessException.class, RestClientException.class},
    maxAttempts = 3,
    backoff = @Backoff(delay = 1000, multiplier = 2, maxDelay = 10000)
)
public User getUser(Long id) {
    return userRepository.findById(id).orElseThrow();
}

Also enable retry in your main application class:
@SpringBootApplication
@EnableRetry
public class GuardApp {
    public static void main(String[] args) {
        SpringApplication.run(GuardApp.class, args);
    }
}'''
            ))
        else:
            # Check specifically for @Backoff annotation (not just configuration)
            has_backoff_annotation = re.search(r'@Backoff\s*\(', content, re.IGNORECASE) is not None

            # Check for exponential backoff parameters
            has_exponential_params = all([
                re.search(r'(delay\s*=|@Backoff.*delay)', content, re.IGNORECASE) is not None,
                re.search(r'multiplier\s*=', content, re.IGNORECASE) is not None,
            ])

            if not has_backoff_annotation:
                # Find the line with retry annotation
                for i, line in enumerate(lines, 1):
                    if any(re.search(pattern, line, re.IGNORECASE) is not None for pattern in self.RETRY_ANNOTATIONS):
                        self.findings.append(Finding(
                            severity='warning',
                            category='backoff',
                            message=f'Retry annotation found but no @Backoff annotation configured',
                            file_path=str(file_path),
                            line_number=i,
                            recommendation='Add @Backoff annotation with exponential backoff: @Retryable(backoff = @Backoff(delay = 1000, multiplier = 2, maxDelay = 10000))'
                        ))
                        break
            elif not has_exponential_params:
                # Has @Backoff but missing exponential parameters
                for i, line in enumerate(lines, 1):
                    if re.search(r'@Backoff', line, re.IGNORECASE) is not None:
                        self.findings.append(Finding(
                            severity='warning',
                            category='backoff',
                            message=f'@Backoff annotation missing exponential parameters (delay, multiplier)',
                            file_path=str(file_path),
                            line_number=i,
                            recommendation='Add exponential parameters: @Backoff(delay = 1000, multiplier = 2, maxDelay = 10000)'
                        ))
                        break

    def _check_hikari_config(self, file_path: Path, content: str, lines: List[str]) -> None:
        """Check for HikariCP connection pool configuration"""
        # Only check files that reference Hikari or datasource config
        if not re.search(r'(HikariConfig|DataSource|spring\.datasource)', content, re.IGNORECASE):
            return

        has_max_lifetime = any(
            re.search(pattern, content, re.IGNORECASE) is not None
            for pattern in self.HIKARI_CONFIG_PATTERNS
        )

        if not has_max_lifetime:
            self.findings.append(Finding(
                severity='warning',
                category='database-ha',
                message=f'{file_path.name} configures datasource but missing max-lifetime for HA failover',
                file_path=str(file_path),
                recommendation='Set spring.datasource.hikari.max-lifetime=30000 (30 seconds) for HA database failover support'
            ))

    def _check_dns_ttl_config(self, file_path: Path, content: str, lines: List[str]) -> None:
        """Check for DNS TTL configuration for HA databases"""
        # Look for main application class
        if not re.search(r'@SpringBootApplication', content):
            return

        has_dns_ttl = any(
            re.search(pattern, content, re.IGNORECASE) is not None
            for pattern in self.DNS_TTL_PATTERNS
        )

        if not has_dns_ttl:
            self.findings.append(Finding(
                severity='error',
                category='database-ha',
                message='Application does not configure DNS TTL for HA database failover',
                file_path=str(file_path),
                recommendation='Add Security.setProperty("networkaddress.cache.ttl", "1") in main() for HA database DNS resolution'
            ))

        # Check for @EnableRetry annotation
        has_enable_retry = re.search(r'@EnableRetry', content, re.IGNORECASE) is not None

        if not has_enable_retry:
            self.findings.append(Finding(
                severity='error',
                category='retry',
                message='Application class missing @EnableRetry annotation',
                file_path=str(file_path),
                recommendation='Add @EnableRetry to your @SpringBootApplication class to enable retry support globally'
            ))

    def _check_application_config(self) -> None:
        """Check application.yml and application.properties for HA settings"""
        config_files = list(self.base_path.rglob("application*.yml")) + \
                      list(self.base_path.rglob("application*.yaml")) + \
                      list(self.base_path.rglob("application*.properties"))

        for config_file in config_files:
            try:
                content = config_file.read_text(encoding='utf-8', errors='ignore')

                # Check HikariCP max-lifetime
                if 'datasource' in content.lower():
                    if not re.search(r'max-lifetime\s*[:=]\s*30000', content, re.IGNORECASE):
                        self.findings.append(Finding(
                            severity='warning',
                            category='database-ha',
                            message=f'{config_file.name} missing optimal max-lifetime setting',
                            file_path=str(config_file),
                            recommendation='Set spring.datasource.hikari.max-lifetime: 30000'
                        ))

                # Check retry configuration
                if 'spring.retry' not in content.lower() and 'resilience4j' not in content.lower():
                    self.findings.append(Finding(
                        severity='info',
                        category='retry',
                        message=f'{config_file.name} does not configure retry framework',
                        file_path=str(config_file),
                        recommendation='Consider adding spring-retry or resilience4j configuration'
                    ))

            except Exception as e:
                self.findings.append(Finding(
                    severity='warning',
                    category='error',
                    message=f'Error reading {config_file.name}: {str(e)}',
                    file_path=str(config_file)
                ))

    def _generate_summary(self, java_files: List[Path]) -> None:
        """Generate summary findings"""
        error_count = sum(1 for f in self.findings if f.severity == 'error')
        warning_count = sum(1 for f in self.findings if f.severity == 'warning')

        self.findings.insert(0, Finding(
            severity='info',
            category='summary',
            message=f'Scanned {len(java_files)} Java files: {error_count} errors, {warning_count} warnings'
        ))


def format_findings(findings: List[Finding]) -> str:
    """Format findings as readable output"""
    output = []

    # Summary first
    summary = [f for f in findings if f.category == 'summary']
    for finding in summary:
        output.append(f"=== {finding.message} ===\n")

    # Group by severity
    errors = [f for f in findings if f.severity == 'error' and f.category != 'summary']
    warnings = [f for f in findings if f.severity == 'warning' and f.category != 'summary']
    infos = [f for f in findings if f.severity == 'info' and f.category != 'summary']

    if errors:
        output.append("\n[ERROR] CRITICAL ERRORS:")
        for finding in errors:
            output.append(f"\n  [{finding.category.upper()}] {finding.message}")
            if finding.file_path:
                loc = f"  [DIR] {finding.file_path}"
                if finding.line_number:
                    loc += f":{finding.line_number}"
                output.append(loc)
            if finding.recommendation:
                output.append(f"\n{finding.recommendation}\n")

    if warnings:
        output.append("\n\n[WARNING] WARNINGS:")
        for finding in warnings:
            output.append(f"\n  [{finding.category.upper()}] {finding.message}")
            if finding.file_path:
                loc = f"  [DIR] {finding.file_path}"
                if finding.line_number:
                    loc += f":{finding.line_number}"
                output.append(loc)
            if finding.recommendation:
                output.append(f"\n{finding.recommendation}\n")

    if infos:
        output.append("\n\n[INFO]  INFO:")
        for finding in infos:
            output.append(f"\n  [{finding.category.upper()}] {finding.message}")
            if finding.file_path:
                output.append(f"  [DIR] {finding.file_path}")
            if finding.recommendation:
                output.append(f"  [TIP] {finding.recommendation}")

    if not errors and not warnings and len(findings) == 1:
        output.append("\n[OK] No HA issues found in Java code!")

    return '\n'.join(output)


def main() -> int:
    """Main entry point"""
    if len(sys.argv) > 1:
        base_path = Path(sys.argv[1])
    else:
        base_path = Path.cwd()

    if not base_path.exists():
        print(f"Error: Path {base_path} does not exist", file=sys.stderr)
        return 1

    print(f"Checking Java Spring Boot HA configuration in: {base_path}\n")

    checker = JavaHAChecker(base_path)
    findings = checker.check_all()

    print(format_findings(findings))

    # Return non-zero if there are errors
    error_count = sum(1 for f in findings if f.severity == 'error')
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
