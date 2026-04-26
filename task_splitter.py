#!/usr/bin/env python3
# task_splitter.py - نظام تقسيم المهام المحسّن مع إدارة التبعيات

import hashlib
import logging
import time
from typing import Dict, Any, List, Tuple, Set, Optional
from dataclasses import dataclass
from enum import Enum
import heapq
from collections import defaultdict, deque

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    print("⚠️ تحذير: networkx غير مثبت - بعض الميزات معطلة")

class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Task:
    """تمثيل مهمة مع البيانات الوصفية"""
    id: str
    function_name: str
    args: tuple
    kwargs: dict
    priority: TaskPriority = TaskPriority.NORMAL
    estimated_duration: float = 1.0  # تقدير بالثواني
    memory_requirement: int = 0  # تقدير بالبايت
    dependencies: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def complexity_score(self) -> float:
        """حساب درجة التعقيد بناءً على المدة والذاكرة"""
        return self.estimated_duration * (1 + self.memory_requirement / (1024 * 1024))  # MB

@dataclass
class TaskCluster:
    """مجموعة مهام مترابطة"""
    id: str
    tasks: List[Task]
    total_complexity: float
    dependencies: Set[str]
    level: int
    can_execute_parallel: bool

class TaskSplitter:
    """نظام تقسيم المهام المحسّن مع إدارة التبعيات"""
    
    def __init__(self, max_cluster_complexity: float = 10.0, max_tasks_per_cluster: int = 5):
        self.setup_logging()
        
        if not HAS_NETWORKX:
            self.logger.warning("networkx غير متوفر - استخدام وضع بسيط")
        
        self.dependency_graph = nx.DiGraph() if HAS_NETWORKX else None
        self.tasks: Dict[str, Task] = {}
        self.max_cluster_complexity = max_cluster_complexity
        self.max_tasks_per_cluster = max_tasks_per_cluster
        self.execution_history: List[Dict[str, Any]] = []
        
    def setup_logging(self):
        """إعداد نظام التسجيل"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/task_splitter.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('TaskSplitter')
    
    def add_task(self, task: Task) -> bool:
        """إضافة مهمة جديدة مع التحقق من الصحة"""
        try:
            if task.id in self.tasks:
                self.logger.warning(f"المهمة {task.id} موجودة مسبقاً، سيتم استبدالها")
            
            # التحقق من وجود التبعيات
            for dep_id in task.dependencies:
                if dep_id not in self.tasks:
                    self.logger.error(f"التبعية {dep_id} غير موجودة للمهمة {task.id}")
                    return False
            
            # إضافة إلى التخزين
            self.tasks[task.id] = task
            
            # إضافة إلى الرسم البياني إذا كان متوفراً
            if self.dependency_graph is not None:
                self.dependency_graph.add_node(task.id, task=task)
                for dep_id in task.dependencies:
                    self.dependency_graph.add_edge(dep_id, task.id)
            
            self.logger.info(f"تمت إضافة المهمة {task.id} مع {len(task.dependencies)} تبعية")
            return True
            
        except Exception as e:
            self.logger.error(f"خطأ في إضافة المهمة {task.id}: {e}")
            return False
    
    def remove_task(self, task_id: str) -> bool:
        """إزالة مهمة مع التبعيات المرتبطة"""
        try:
            if task_id not in self.tasks:
                self.logger.warning(f"المهمة {task_id} غير موجودة")
                return False
            
            # إزالة من الرسم البياني أولاً
            if self.dependency_graph is not None and self.dependency_graph.has_node(task_id):
                self.dependency_graph.remove_node(task_id)
            
            # إزالة من التخزين
            del self.tasks[task_id]
            
            self.logger.info(f"تمت إزالة المهمة {task_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"خطأ في إزالة المهمة {task_id}: {e}")
            return False
    
    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """التحقق من صحة التبعيات وإيجاد الدورات"""
        if not HAS_NETWORKX or self.dependency_graph is None:
            return True, []  # لا توجد دورات إذا لم يكن هناك رسم بياني
        
        try:
            # البحث عن دورات
            cycles = list(nx.simple_cycles(self.dependency_graph))
            if cycles:
                self.logger.error(f"تم اكتشاف دورات في التبعيات: {cycles}")
                return False, cycles
            
            # التحقق من التبعيات المفقودة
            missing_deps = []
            for node in self.dependency_graph.nodes():
                task = self.tasks.get(node)
                if task:
                    for dep in task.dependencies:
                        if dep not in self.tasks:
                            missing_deps.append(f"{node} -> {dep}")
            
            if missing_deps:
                self.logger.error(f"تبعيات مفقودة: {missing_deps}")
                return False, missing_deps
            
            return True, []
            
        except Exception as e:
            self.logger.error(f"خطأ في التحقق من التبعيات: {e}")
            return False, [str(e)]
    
    def calculate_critical_path(self) -> List[str]:
        """حساب المسار الحرج للمهام"""
        if not HAS_NETWORKX or self.dependency_graph is None:
            return []
        
        try:
            # حساب أطول مسار (المسار الحرج)
            if nx.is_directed_acyclic_graph(self.dependency_graph):
                longest_path = nx.dag_longest_path(self.dependency_graph, weight='duration')
                return longest_path
            return []
        except Exception as e:
            self.logger.warning(f"خطأ في حساب المسار الحرج: {e}")
            return []
    
    def split_tasks_advanced(self, strategy: str = "balanced") -> Dict[str, TaskCluster]:
        """تقسيم المهام باستخدام استراتيجيات متقدمة"""
        self.logger.info(f"بدء تقسيم المهام باستخدام استراتيجية: {strategy}")
        
        # التحقق من صحة التبعيات أولاً
        is_valid, issues = self.validate_dependencies()
        if not is_valid:
            self.logger.error(f"لا يمكن تقسيم المهام بسبب مشاكل في التبعيات: {issues}")
            return {}
        
        if not HAS_NETWORKX or self.dependency_graph is None:
            return self._split_simple()
        
        try:
            if strategy == "balanced":
                return self._split_balanced()
            elif strategy == "parallel_max":
                return self._split_parallel_max()
            elif strategy == "memory_optimized":
                return self._split_memory_optimized()
            else:
                self.logger.warning(f"استراتيجية {strategy} غير معروفة، استخدام متوازن")
                return self._split_balanced()
                
        except Exception as e:
            self.logger.error(f"خطأ في تقسيم المهام: {e}")
            return self._split_simple()
    
    def _split_simple(self) -> Dict[str, TaskCluster]:
        """تقسيم بسيط بدون networkx"""
        clusters = {}
        
        # تجميع المهام بدون تبعيات أولاً
        independent_tasks = [task for task in self.tasks.values() if not task.dependencies]
        
        if independent_tasks:
            cluster_id = self._generate_cluster_id(independent_tasks, 0)
            clusters[cluster_id] = TaskCluster(
                id=cluster_id,
                tasks=independent_tasks,
                total_complexity=sum(t.complexity_score for t in independent_tasks),
                dependencies=set(),
                level=0,
                can_execute_parallel=True
            )
        
        # المهام المتبقية
        remaining_tasks = [task for task in self.tasks.values() if task.dependencies]
        if remaining_tasks:
            cluster_id = self._generate_cluster_id(remaining_tasks, 1)
            clusters[cluster_id] = TaskCluster(
                id=cluster_id,
                tasks=remaining_tasks,
                total_complexity=sum(t.complexity_score for t in remaining_tasks),
                dependencies=set(dep for task in remaining_tasks for dep in task.dependencies),
                level=1,
                can_execute_parallel=False
            )
        
        return clusters
    
    def _split_balanced(self) -> Dict[str, TaskCluster]:
        """تقسيم متوازن مع مراعاة التعقيد"""
        clusters = {}
        
        if not HAS_NETWORKX or self.dependency_graph is None:
            return self._split_simple()
        
        # الحصول على المستويات الطوبولوجية
        try:
            levels = list(nx.topological_generations(self.dependency_graph))
        except nx.NetworkXError as e:
            self.logger.error(f"خطأ في المستويات الطوبولوجية: {e}")
            return self._split_simple()
        
        for level_num, level_nodes in enumerate(levels):
            level_tasks = [self.tasks[node] for node in level_nodes]
            
            # تقسيم المهام في هذا المستوى إلى مجموعات متوازنة
            current_cluster_tasks = []
            current_complexity = 0.0
            
            for task in sorted(level_tasks, key=lambda t: t.complexity_score, reverse=True):
                if (current_complexity + task.complexity_score > self.max_cluster_complexity or
                    len(current_cluster_tasks) >= self.max_tasks_per_cluster):
                    
                    # إنشاء مجموعة جديدة
                    if current_cluster_tasks:
                        cluster_id = self._generate_cluster_id(current_cluster_tasks, level_num)
                        clusters[cluster_id] = TaskCluster(
                            id=cluster_id,
                            tasks=current_cluster_tasks.copy(),
                            total_complexity=current_complexity,
                            dependencies=self._get_cluster_dependencies(current_cluster_tasks),
                            level=level_num,
                            can_execute_parallel=True
                        )
                    
                    current_cluster_tasks = []
                    current_complexity = 0.0
                
                current_cluster_tasks.append(task)
                current_complexity += task.complexity_score
            
            # إضافة المجموعة المتبقية
            if current_cluster_tasks:
                cluster_id = self._generate_cluster_id(current_cluster_tasks, level_num)
                clusters[cluster_id] = TaskCluster(
                    id=cluster_id,
                    tasks=current_cluster_tasks,
                    total_complexity=current_complexity,
                    dependencies=self._get_cluster_dependencies(current_cluster_tasks),
                    level=level_num,
                    can_execute_parallel=True
                )
        
        return clusters
    
    def _split_parallel_max(self) -> Dict[str, TaskCluster]:
        """تقسيم لزيادة التوازي مع تقليل التبعيات"""
        clusters = {}
        
        if not HAS_NETWORKX or self.dependency_graph is None:
            return self._split_simple()
        
        # تجميع المهام التي يمكن تنفيذها معاً
        independent_sets = self._find_independent_sets()
        
        for set_num, task_set in enumerate(independent_sets):
            cluster_id = f"parallel_set_{set_num}"
            tasks_list = [self.tasks[task_id] for task_id in task_set]
            
            clusters[cluster_id] = TaskCluster(
                id=cluster_id,
                tasks=tasks_list,
                total_complexity=sum(t.complexity_score for t in tasks_list),
                dependencies=self._get_cluster_dependencies(tasks_list),
                level=set_num,
                can_execute_parallel=True
            )
        
        return clusters
    
    def _split_memory_optimized(self) -> Dict[str, TaskCluster]:
        """تقسيم مُحسّن للذاكرة"""
        clusters = {}
        
        if not HAS_NETWORKX or self.dependency_graph is None:
            return self._split_simple()
        
        # ترتيب المهام حسب متطلبات الذاكرة
        memory_intensive_tasks = sorted(
            [task for task in self.tasks.values() if task.memory_requirement > 0],
            key=lambda t: t.memory_requirement,
            reverse=True
        )
        
        regular_tasks = [task for task in self.tasks.values() if task.memory_requirement == 0]
        
        # معالجة المهام كثيفة الذاكرة في مجموعات منفصلة
        memory_clusters = self._cluster_by_memory(memory_intensive_tasks)
        clusters.update(memory_clusters)
        
        # معالجة المهام العادية
        regular_clusters = self._cluster_regular_tasks(regular_tasks)
        clusters.update(regular_clusters)
        
        return clusters
    
    def _find_independent_sets(self) -> List[Set[str]]:
        """إيجاد مجموعات المهام المستقلة"""
        if not HAS_NETWORKX or self.dependency_graph is None:
            return []
        
        # استخدام تلوين الرسم البياني لإيجاد مجموعات مستقلة
        try:
            independent_sets = []
            graph = self.dependency_graph.to_undirected()
            
            # خوارزمية بسيطة لإيجاد مجموعات مستقلة
            remaining_nodes = set(graph.nodes())
            
            while remaining_nodes:
                # اختيار عقدة وبناء مجموعة مستقلة
                independent_set = set()
                candidates = remaining_nodes.copy()
                
                while candidates:
                    node = next(iter(candidates))
                    independent_set.add(node)
                    
                    # إزالة العقدة المجاورة
                    candidates -= set(graph.neighbors(node)) | {node}
                
                independent_sets.append(independent_set)
                remaining_nodes -= independent_set
            
            return independent_sets
            
        except Exception as e:
            self.logger.warning(f"خطأ في إيجاد المجموعات المستقلة: {e}")
            return [set(self.tasks.keys())]
    
    def _cluster_by_memory(self, tasks: List[Task]) -> Dict[str, TaskCluster]:
        """تجميع المهام حسب متطلبات الذاكرة"""
        clusters = {}
        memory_limit = 100 * 1024 * 1024  # 100 MB حد افتراضي
        
        current_memory = 0
        current_tasks = []
        cluster_num = 0
        
        for task in tasks:
            if current_memory + task.memory_requirement > memory_limit and current_tasks:
                # إنشاء مجموعة جديدة
                cluster_id = f"memory_cluster_{cluster_num}"
                clusters[cluster_id] = TaskCluster(
                    id=cluster_id,
                    tasks=current_tasks.copy(),
                    total_complexity=sum(t.complexity_score for t in current_tasks),
                    dependencies=self._get_cluster_dependencies(current_tasks),
                    level=cluster_num,
                    can_execute_parallel=False  # تنفيذ تسلسلي للحفاظ على الذاكرة
                )
                current_tasks = []
                current_memory = 0
                cluster_num += 1
            
            current_tasks.append(task)
            current_memory += task.memory_requirement
        
        # المجموعة المتبقية
        if current_tasks:
            cluster_id = f"memory_cluster_{cluster_num}"
            clusters[cluster_id] = TaskCluster(
                id=cluster_id,
                tasks=current_tasks,
                total_complexity=sum(t.complexity_score for t in current_tasks),
                dependencies=self._get_cluster_dependencies(current_tasks),
                level=cluster_num,
                can_execute_parallel=False
            )
        
        return clusters
    
    def _cluster_regular_tasks(self, tasks: List[Task]) -> Dict[str, TaskCluster]:
        """تجميع المهام العادية"""
        if not tasks:
            return {}
        
        # استخدام التقسيم المتوازن للمهام العادية
        temp_splitter = TaskSplitter()
        for task in tasks:
            temp_splitter.add_task(task)
        
        return temp_splitter._split_balanced()
    
    def _get_cluster_dependencies(self, tasks: List[Task]) -> Set[str]:
        """الحصول على تبعيات مجموعة المهام"""
        dependencies = set()
        for task in tasks:
            dependencies.update(task.dependencies)
        return dependencies
    
    def _generate_cluster_id(self, tasks: List[Task], level: int) -> str:
        """إنشاء معرف فريد للمجموعة"""
        task_ids = ','.join(sorted(task.id for task in tasks))
        deps_hash = hashlib.md5(task_ids.encode()).hexdigest()[:8]
        return f"L{level}-{deps_hash}"
    
    def get_execution_plan(self, clusters: Dict[str, TaskCluster]) -> List[List[str]]:
        """إنشاء خطة تنفيذ مرتبة"""
        if not clusters:
            return []
        
        # تجميع المجموعات حسب المستوى
        levels = defaultdict(list)
        for cluster in clusters.values():
            levels[cluster.level].append(cluster.id)
        
        # ترتيب المستويات
        execution_plan = []
        for level in sorted(levels.keys()):
            execution_plan.append(levels[level])
        
        return execution_plan
    
    def optimize_execution_order(self, clusters: Dict[str, TaskCluster]) -> List[str]:
        """تحسين ترتيب التنفيذ بناءً على التعقيد والتبعيات"""
        if not clusters:
            return []
        
        # ترتيب المجموعات حسب التعقيد (الأكبر أولاً) مع مراعاة التبعيات
        ordered_clusters = []
        
        for cluster in clusters.values():
            heapq.heappush(ordered_clusters, (-cluster.total_complexity, cluster.id, cluster))
        
        execution_order = []
        while ordered_clusters:
            _, cluster_id, cluster = heapq.heappop(ordered_clusters)
            execution_order.append(cluster_id)
        
        return execution_order
    
    def get_statistics(self) -> Dict[str, Any]:
        """الحصول على إحصائيات المهام"""
        total_tasks = len(self.tasks)
        total_dependencies = sum(len(task.dependencies) for task in self.tasks.values())
        
        return {
            "total_tasks": total_tasks,
            "total_dependencies": total_dependencies,
            "avg_dependencies_per_task": total_dependencies / total_tasks if total_tasks > 0 else 0,
            "tasks_without_dependencies": len([t for t in self.tasks.values() if not t.dependencies]),
            "max_dependencies": max(len(t.dependencies) for t in self.tasks.values()) if self.tasks else 0,
            "total_complexity": sum(t.complexity_score for t in self.tasks.values()),
            "graph_available": HAS_NETWORKX and self.dependency_graph is not None
        }

# استخدام مبسط
def create_task(task_id: str, function_name: str, args: tuple = (), kwargs: dict = None, 
               dependencies: List[str] = None, **metadata) -> Task:
    """دالة مساعدة لإنشاء مهام"""
    return Task(
        id=task_id,
        function_name=function_name,
        args=args or (),
        kwargs=kwargs or {},
        dependencies=dependencies or [],
        metadata=metadata or {}
    )

# مثال على الاستخدام
if __name__ == "__main__":
    splitter = TaskSplitter()
    
    # إنشاء مهام مثال
    tasks = [
        create_task("task1", "process_data", (100,), {}, priority=TaskPriority.HIGH),
        create_task("task2", "analyze_data", (200,), {}, dependencies=["task1"]),
        create_task("task3", "generate_report", (300,), {}, dependencies=["task2"]),
        create_task("task4", "backup_data", (400,), {}),  # مهمة مستقلة
    ]
    
    # إضافة المهام
    for task in tasks:
        splitter.add_task(task)
    
    # تقسيم المهام
    clusters = splitter.split_tasks_advanced("balanced")
    
    print("📊 إحصائيات المهام:")
    stats = splitter.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n🔧 المجموعات المنشأة:")
    for cluster_id, cluster in clusters.items():
        print(f"  {cluster_id}: {len(cluster.tasks)} مهام, التعقيد: {cluster.total_complexity:.2f}")
    
    print("\n📋 خطة التنفيذ:")
    execution_plan = splitter.get_execution_plan(clusters)
    for i, level in enumerate(execution_plan):
        print(f"  المستوى {i}: {level}")