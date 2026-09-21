#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///

"""
Kubernetes Manifest HA Configuration Checker

Analyzes Kubernetes manifests to verify high availability best practices:
- HPA (Horizontal Pod Autoscaler)
- PDB (Pod Disruption Budget)
- Topology spread constraints
- Anti-affinity rules
- Resource limits and requests
- Multiple replicas
- Readiness and liveness probes
- Image pull policy
"""

import sys
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class Finding:
    """Represents an HA check finding"""
    severity: str  # 'error', 'warning', 'info'
    category: str
    message: str
    file_path: Optional[str] = None
    resource_name: Optional[str] = None
    recommendation: Optional[str] = None


class K8sHAChecker:
    """Checks Kubernetes manifests for HA patterns"""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.findings: List[Finding] = []
        self.deployments: List[Dict[str, Any]] = []
        self.has_hpa = False
        self.has_pdb = False
        self.hpa_min_replicas: Dict[str, int] = {}  # Map deployment name to minReplicas
        self.kustomize_bases: Dict[str, Path] = {}  # Map patch dirs to their base dirs
        self.kustomize_patches: set = set()  # Set of patch file paths

    def check_all(self) -> List[Finding]:
        """Run all checks and return findings"""
        self.findings = []

        # Check if this is a Gradle project that generates K8s manifests
        self._check_gradle_project()

        # Parse kustomization files to understand base/patch relationships
        self._parse_kustomizations()

        # Find all Kubernetes manifest files
        manifest_files = self._find_k8s_manifests()

        if not manifest_files:
            self.findings.append(Finding(
                severity='info',
                category='discovery',
                message=f'No Kubernetes manifests found in {self.base_path}'
            ))
            return self.findings

        # First pass: collect HPA information before checking deployments
        for manifest_file in manifest_files:
            self._collect_hpa_info(manifest_file)

        # Second pass: check each manifest with HPA context
        for manifest_file in manifest_files:
            self._check_manifest_file(manifest_file)

        # Cross-resource checks
        self._check_cross_resource()

        # Generate summary
        self._generate_summary(manifest_files)

        return self.findings

    def _collect_hpa_info(self, file_path: Path) -> None:
        """First pass to collect HPA minReplicas before checking deployments"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                docs = list(yaml.safe_load_all(f))

            for doc in docs:
                if not doc or not isinstance(doc, dict):
                    continue

                kind = doc.get('kind', '')
                if kind == 'HorizontalPodAutoscaler':
                    self.has_hpa = True
                    spec = doc.get('spec', {})
                    target_ref = spec.get('scaleTargetRef', {})
                    target_name = target_ref.get('name', '')
                    min_replicas = spec.get('minReplicas', 1)
                    if target_name:
                        # Keep the maximum minReplicas if multiple HPAs for same deployment
                        self.hpa_min_replicas[target_name] = max(
                            self.hpa_min_replicas.get(target_name, 0),
                            min_replicas
                        )
        except Exception as e:
            print(f"Error parsing {file_path}: {e}", file=sys.stderr)

    def _parse_kustomizations(self) -> None:
        """Parse kustomization.yaml files to identify patches and base resources"""
        kustomization_files = list(self.base_path.rglob("kustomization.yaml"))

        for kust_file in kustomization_files:
            try:
                with open(kust_file, 'r', encoding='utf-8') as f:
                    kust_data = yaml.safe_load(f)
                    if not kust_data:
                        continue

                    kust_dir = kust_file.parent

                    # Track base resources
                    resources = kust_data.get('resources', [])
                    for resource in resources:
                        if resource.startswith('../') or resource.startswith('../../'):
                            # This is a reference to a base directory
                            base_path = (kust_dir / resource).resolve()
                            self.kustomize_bases[str(kust_dir)] = base_path

                    # Track patches
                    patches = kust_data.get('patchesStrategicMerge', [])
                    for patch in patches:
                        patch_path = kust_dir / patch
                        self.kustomize_patches.add(str(patch_path.resolve()))

            except Exception as e:
                print(f"Error parsing {kust_file}: {e}", file=sys.stderr)

    def _check_gradle_project(self) -> None:
        """Check if this is a Gradle project with generateKubeTemplates task"""
        build_gradle = self.base_path / "build.gradle"
        gradle_dir = self.base_path / "gradle"
        build_k8s_dir = self.base_path / "build" / "k8s"

        # Check if this is a Gradle project with K8s generation
        if build_gradle.exists() or gradle_dir.exists():
            # Look for generateKubeTemplates or novadeploy plugin references
            if build_gradle.exists():
                content = build_gradle.read_text(encoding='utf-8', errors='ignore')
                has_k8s_gen = any([
                    'generateKubeTemplates' in content,
                    'com.guidewire.novadeploy' in content,
                    'novaDeploy' in content,
                ])

                if has_k8s_gen and not build_k8s_dir.exists():
                    self.findings.append(Finding(
                        severity='info',
                        category='discovery',
                        message='Gradle K8s manifest generation detected but build/k8s/ not found',
                        recommendation='Run "./gradlew generateKubeTemplates" to generate K8s manifests before checking'
                    ))

    def _find_k8s_manifests(self) -> List[Path]:
        """Find all K8s manifest files"""
        manifest_files = []

        # Priority 1: Check for Gradle-generated manifests (if build/k8s exists)
        gradle_k8s_dir = self.base_path / "build" / "k8s"
        if gradle_k8s_dir.exists() and gradle_k8s_dir.is_dir():
            print(f"  [INFO]  Found Gradle-generated manifests in build/k8s/")
            manifest_files.extend(gradle_k8s_dir.rglob("*.yaml"))
            manifest_files.extend(gradle_k8s_dir.rglob("*.yml"))

        # Priority 2: Check kustomization directories (k8s/*/)
        # These contain overlays that patch the base manifests
        k8s_dir = self.base_path / "k8s"
        if k8s_dir.exists() and k8s_dir.is_dir():
            for env_dir in k8s_dir.iterdir():
                if env_dir.is_dir():
                    # Check for kustomization.yaml
                    kustomization_file = env_dir / "kustomization.yaml"
                    if kustomization_file.exists():
                        print(f"  [INFO]  Found kustomization overlay in k8s/{env_dir.name}/")
                        # Add patch files from kustomization overlay
                        manifest_files.extend(env_dir.rglob("*.yaml"))
                        manifest_files.extend(env_dir.rglob("*.yml"))

        # Priority 3: Common patterns for other K8s manifests
        patterns = [
            "**/*deployment*.yaml",
            "**/*deployment*.yml",
            "**/kubernetes/**/*.yaml",
            "**/kubernetes/**/*.yml",
            "**/manifests/**/*.yaml",
            "**/manifests/**/*.yml",
            "**/*-deployment.yaml",
            "**/*-deployment.yml",
        ]

        for pattern in patterns:
            manifest_files.extend(self.base_path.glob(pattern))

        # Remove duplicates while preserving order
        seen = set()
        unique_files = []
        for f in manifest_files:
            if f not in seen:
                seen.add(f)
                unique_files.append(f)

        return unique_files

    def _check_manifest_file(self, file_path: Path) -> None:
        """Check a single manifest file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Handle multi-document YAML
                docs = list(yaml.safe_load_all(f))

            for doc in docs:
                if not doc or not isinstance(doc, dict):
                    continue

                kind = doc.get('kind', '')
                metadata = doc.get('metadata', {})
                resource_name = metadata.get('name', 'unknown')

                if kind == 'Deployment':
                    self.deployments.append({
                        'file': file_path,
                        'name': resource_name,
                        'spec': doc
                    })
                    self._check_deployment(doc, file_path, resource_name)

                elif kind == 'StatefulSet':
                    self._check_statefulset(doc, file_path, resource_name)

                elif kind == 'HorizontalPodAutoscaler':
                    self.has_hpa = True
                    # Track minReplicas for deployments
                    spec = doc.get('spec', {})
                    target_ref = spec.get('scaleTargetRef', {})
                    target_name = target_ref.get('name', '')
                    min_replicas = spec.get('minReplicas', 1)
                    if target_name:
                        self.hpa_min_replicas[target_name] = min_replicas
                    self._check_hpa(doc, file_path, resource_name)

                elif kind == 'PodDisruptionBudget':
                    self.has_pdb = True
                    self._check_pdb(doc, file_path, resource_name)

        except yaml.YAMLError as e:
            self.findings.append(Finding(
                severity='error',
                category='parse',
                message=f'YAML parsing error in {file_path.name}: {str(e)}',
                file_path=str(file_path)
            ))
        except Exception as e:
            self.findings.append(Finding(
                severity='warning',
                category='error',
                message=f'Error reading {file_path.name}: {str(e)}',
                file_path=str(file_path)
            ))

    def _check_deployment(self, doc: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check Deployment for HA configuration"""
        spec = doc.get('spec', {})
        template = spec.get('template', {})
        template_spec = template.get('spec', {})
        containers = template_spec.get('containers', [])

        # Check replicas (but be aware that kustomize patches may not show full spec)
        replicas = spec.get('replicas', 1)

        # Detect if this is a kustomize patch file (partial spec)
        is_patch = 'patch' in str(file_path).lower() or len(spec) < 3

        # Check if there's an HPA covering this deployment with adequate minReplicas
        hpa_min_replicas = self.hpa_min_replicas.get(resource_name, 0)
        has_adequate_hpa = hpa_min_replicas >= 2

        if replicas < 2 and not is_patch and not has_adequate_hpa:
            self.findings.append(Finding(
                severity='warning',
                category='replication',
                message=f'Deployment has only {replicas} replica(s)',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Set spec.replicas >= 2 for high availability, or configure HPA'
            ))
        elif is_patch and replicas == 1 and not has_adequate_hpa:
            # For patches, provide info rather than warning since base might have more replicas
            self.findings.append(Finding(
                severity='info',
                category='replication',
                message=f'Kustomize patch sets {replicas} replica(s) - verify HPA or base manifest has >= 2',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Ensure base deployment or HPA maintains >= 2 replicas for HA'
            ))

        # Check resource limits
        self._check_resources(containers, file_path, resource_name)

        # Check probes
        self._check_probes(containers, file_path, resource_name)

        # Check topology spread constraints
        self._check_topology_spread(template_spec, file_path, resource_name)

        # Check anti-affinity
        self._check_affinity(template_spec, file_path, resource_name)

        # Check image pull policy
        self._check_image_pull_policy(containers, file_path, resource_name)

    def _check_statefulset(self, doc: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check StatefulSet for HA configuration"""
        spec = doc.get('spec', {})
        template = spec.get('template', {})
        template_spec = template.get('spec', {})
        containers = template_spec.get('containers', [])

        # Check replicas
        replicas = spec.get('replicas', 1)
        if replicas < 2:
            self.findings.append(Finding(
                severity='warning',
                category='replication',
                message=f'StatefulSet has only {replicas} replica(s)',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Set spec.replicas >= 2 for high availability'
            ))

        # Check resources and probes
        self._check_resources(containers, file_path, resource_name)
        self._check_probes(containers, file_path, resource_name)

    def _check_resources(self, containers: List[Dict[str, Any]], file_path: Path, resource_name: str) -> None:
        """Check resource requests and limits"""
        # Skip if this is a kustomize patch (resources may be in base)
        is_patch = str(file_path.resolve()) in self.kustomize_patches

        for container in containers:
            container_name = container.get('name', 'unknown')
            resources = container.get('resources', {})
            requests = resources.get('requests', {})
            limits = resources.get('limits', {})

            # Only report if not a patch, or if patch explicitly sets empty resources
            if not requests and not is_patch:
                self.findings.append(Finding(
                    severity='warning',
                    category='resources',
                    message=f'Container "{container_name}" missing resource requests',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Add resources.requests for memory and cpu to ensure proper scheduling'
                ))

            if not limits and not is_patch:
                self.findings.append(Finding(
                    severity='warning',
                    category='resources',
                    message=f'Container "{container_name}" missing resource limits',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Add resources.limits for memory and cpu to prevent resource exhaustion'
                ))

    def _check_probes(self, containers: List[Dict[str, Any]], file_path: Path, resource_name: str) -> None:
        """Check liveness and readiness probes"""
        # Skip if this is a kustomize patch (probes may be in base)
        is_patch = str(file_path.resolve()) in self.kustomize_patches

        for container in containers:
            container_name = container.get('name', 'unknown')

            if 'livenessProbe' not in container and not is_patch:
                self.findings.append(Finding(
                    severity='warning',
                    category='probes',
                    message=f'Container "{container_name}" missing livenessProbe',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Add livenessProbe to enable automatic restart of unhealthy pods'
                ))

            if 'readinessProbe' not in container and not is_patch:
                self.findings.append(Finding(
                    severity='warning',
                    category='probes',
                    message=f'Container "{container_name}" missing readinessProbe',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Add readinessProbe to prevent traffic to non-ready pods'
                ))

    def _check_topology_spread(self, template_spec: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check topology spread constraints"""
        topology_spread = template_spec.get('topologySpreadConstraints', [])

        # Skip if this is a kustomize patch
        is_patch = str(file_path.resolve()) in self.kustomize_patches

        if not topology_spread and not is_patch:
            self.findings.append(Finding(
                severity='error',
                category='distribution',
                message=f'No topologySpreadConstraints defined - pods may be scheduled in single AZ',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='''Add topologySpreadConstraints to distribute pods across availability zones:

spec:
  template:
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: guard-app
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: ScheduleAnyway
        labelSelector:
          matchLabels:
            app: guard-app

This ensures pods are distributed across AZs and nodes for maximum availability.'''
            ))
        elif topology_spread:
            # Check for zone distribution
            has_zone_spread = any(
                constraint.get('topologyKey') == 'topology.kubernetes.io/zone'
                for constraint in topology_spread
            )
            if not has_zone_spread and not is_patch:
                self.findings.append(Finding(
                    severity='error',
                    category='distribution',
                    message=f'topologySpreadConstraints missing zone distribution',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Add constraint with topologyKey: topology.kubernetes.io/zone to distribute across AZs'
                ))

    def _check_affinity(self, template_spec: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check pod anti-affinity rules"""
        affinity = template_spec.get('affinity', {})
        pod_anti_affinity = affinity.get('podAntiAffinity', {})

        # Skip if this is a kustomize patch
        is_patch = str(file_path.resolve()) in self.kustomize_patches

        if not pod_anti_affinity and not is_patch:
            self.findings.append(Finding(
                severity='error',
                category='distribution',
                message=f'No podAntiAffinity rules defined - replicas may be co-located on same node',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='''Add podAntiAffinity to prevent scheduling multiple replicas on the same node:

spec:
  template:
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchLabels:
                  app: guard-app
              topologyKey: kubernetes.io/hostname

Use 'preferred' for soft anti-affinity (allows overcommitting if needed) or 'required' for hard anti-affinity:

          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: guard-app
            topologyKey: kubernetes.io/hostname

This prevents single node failure from taking down multiple replicas.'''
            ))

    def _check_image_pull_policy(self, containers: List[Dict[str, Any]], file_path: Path, resource_name: str) -> None:
        """Check image pull policy for HA"""
        for container in containers:
            container_name = container.get('name', 'unknown')
            image_pull_policy = container.get('imagePullPolicy', 'Always')

            if image_pull_policy not in ['IfNotPresent', 'Never']:
                self.findings.append(Finding(
                    severity='info',
                    category='image',
                    message=f'Container "{container_name}" imagePullPolicy is "{image_pull_policy}"',
                    file_path=str(file_path),
                    resource_name=resource_name,
                    recommendation='Consider imagePullPolicy: IfNotPresent to use cached images during registry unavailability'
                ))

    def _check_hpa(self, doc: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check HPA configuration"""
        spec = doc.get('spec', {})
        min_replicas = spec.get('minReplicas', 1)
        max_replicas = spec.get('maxReplicas', 1)

        if min_replicas < 2:
            self.findings.append(Finding(
                severity='warning',
                category='hpa',
                message=f'HPA minReplicas is {min_replicas}',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Set minReplicas >= 2 for high availability'
            ))

        if max_replicas < min_replicas * 2:
            self.findings.append(Finding(
                severity='info',
                category='hpa',
                message=f'HPA maxReplicas ({max_replicas}) may be too low',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Consider setting maxReplicas higher for better scaling headroom'
            ))

    def _check_pdb(self, doc: Dict[str, Any], file_path: Path, resource_name: str) -> None:
        """Check PDB configuration"""
        spec = doc.get('spec', {})

        if 'minAvailable' not in spec and 'maxUnavailable' not in spec:
            self.findings.append(Finding(
                severity='error',
                category='pdb',
                message=f'PDB missing both minAvailable and maxUnavailable',
                file_path=str(file_path),
                resource_name=resource_name,
                recommendation='Set either minAvailable or maxUnavailable to protect against disruptions'
            ))

    def _check_cross_resource(self) -> None:
        """Check for missing cross-resource configurations"""
        if self.deployments and not self.has_hpa:
            self.findings.append(Finding(
                severity='warning',
                category='hpa',
                message='Deployments found but no HorizontalPodAutoscaler defined',
                recommendation='Create HPA to enable automatic scaling based on metrics'
            ))

        if self.deployments and not self.has_pdb:
            self.findings.append(Finding(
                severity='warning',
                category='pdb',
                message='Deployments found but no PodDisruptionBudget defined',
                recommendation='Create PDB to ensure availability during maintenance and updates'
            ))

    def _generate_summary(self, manifest_files: List[Path]) -> None:
        """Generate summary findings"""
        error_count = sum(1 for f in self.findings if f.severity == 'error')
        warning_count = sum(1 for f in self.findings if f.severity == 'warning')

        self.findings.insert(0, Finding(
            severity='info',
            category='summary',
            message=f'Scanned {len(manifest_files)} K8s manifest files: {error_count} errors, {warning_count} warnings'
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
            if finding.resource_name:
                output.append(f"  [PACKAGE] Resource: {finding.resource_name}")
            if finding.file_path:
                output.append(f"  [DIR] {finding.file_path}")
            if finding.recommendation:
                output.append(f"\n{finding.recommendation}\n")

    if warnings:
        output.append("\n\n[WARNING] WARNINGS:")
        for finding in warnings:
            output.append(f"\n  [{finding.category.upper()}] {finding.message}")
            if finding.resource_name:
                output.append(f"  [PACKAGE] Resource: {finding.resource_name}")
            if finding.file_path:
                output.append(f"  [DIR] {finding.file_path}")
            if finding.recommendation:
                output.append(f"\n{finding.recommendation}\n")

    if infos:
        output.append("\n\n[INFO]  INFO:")
        for finding in infos:
            output.append(f"\n  [{finding.category.upper()}] {finding.message}")
            if finding.resource_name:
                output.append(f"  [PACKAGE] Resource: {finding.resource_name}")
            if finding.file_path:
                output.append(f"  [DIR] {finding.file_path}")
            if finding.recommendation:
                output.append(f"  [TIP] {finding.recommendation}")

    if not errors and not warnings and len(findings) == 1:
        output.append("\n[OK] No HA issues found in K8s manifests!")

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

    print(f"Checking Kubernetes manifest HA configuration in: {base_path}\n")

    checker = K8sHAChecker(base_path)
    findings = checker.check_all()

    print(format_findings(findings))

    # Always exit 0 -- findings are advisory, not failures
    return 0


if __name__ == "__main__":
    sys.exit(main())
