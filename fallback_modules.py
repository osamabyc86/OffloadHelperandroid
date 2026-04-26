# fallback_modules.py - وحدات بديلة للاعتماديات المفقودة
import time
import math
import random
import sys
import os

class FakeNumpy:
    """محاكاة numpy الأساسية"""
    
    class random:
        """محاكاة numpy.random"""
        @staticmethod
        def rand(*size):
            if len(size) == 0:
                return random.random()
            elif len(size) == 1:
                # حالة size كمفرد
                if isinstance(size[0], int):
                    return [random.random() for _ in range(size[0])]
                elif isinstance(size[0], tuple):
                    # إذا كان tuple ممرر كوسيطة واحدة
                    if len(size[0]) == 1:
                        return [random.random() for _ in range(size[0][0])]
                    elif len(size[0]) == 2:
                        return [[random.random() for _ in range(size[0][1])] for _ in range(size[0][0])]
            elif len(size) == 2:
                # حالة (m, n)
                return [[random.random() for _ in range(size[1])] for _ in range(size[0])]
            else:
                raise ValueError(f"حجم غير مدعوم: {size}")
        
        @staticmethod
        def randn(*size):
            """مولد أرقام عشوائية بتوزيع طبيعي (متوسط 0، انحراف معياري 1)"""
            if len(size) == 0:
                return random.gauss(0, 1)
            elif len(size) == 1:
                if isinstance(size[0], int):
                    return [random.gauss(0, 1) for _ in range(size[0])]
                elif isinstance(size[0], tuple):
                    if len(size[0]) == 1:
                        return [random.gauss(0, 1) for _ in range(size[0][0])]
                    elif len(size[0]) == 2:
                        return [[random.gauss(0, 1) for _ in range(size[0][1])] for _ in range(size[0][0])]
            elif len(size) == 2:
                return [[random.gauss(0, 1) for _ in range(size[1])] for _ in range(size[0])]
            return random.gauss(0, 1)
    
    @staticmethod
    def dot(a, b):
        """ضرب نقطي أو مصفوفي"""
        # تحويل tuples إلى lists إذا لزم الأمر
        if isinstance(a, tuple):
            a = list(a)
        if isinstance(b, tuple):
            b = list(b)
            
        if isinstance(a[0], (list, tuple)) and isinstance(b[0], (list, tuple)):
            # ضرب مصفوفات
            result = []
            for i in range(len(a)):
                row = []
                for j in range(len(b[0])):
                    sum_val = 0
                    for k in range(len(b)):
                        sum_val += a[i][k] * b[k][j]
                    row.append(sum_val)
                result.append(row)
            return result
        else:
            # ضرب نقطي
            return sum(x * y for x, y in zip(a, b))
    
    @staticmethod
    def mean(data, axis=None):
        """حساب المتوسط"""
        if axis is None:
            return sum(data) / len(data)
        # تبسيط معالجة المحاور
        return sum(data) / len(data)
    
    @staticmethod
    def std(data, axis=None, ddof=0):
        """حساب الانحراف المعياري"""
        mean_val = sum(data) / len(data)
        n = len(data)
        variance = sum((x - mean_val) ** 2 for x in data) / (n - ddof)
        return math.sqrt(variance)
    
    @staticmethod
    def array(data, dtype=None):
        """محاكاة np.array"""
        # نسخة مبسطة
        if isinstance(data, (list, tuple)):
            if data and isinstance(data[0], (list, tuple)):
                # مصفوفة ثنائية
                return [list(row) for row in data]
        return list(data) if isinstance(data, tuple) else data
    
    @staticmethod
    def zeros(shape):
        """مصفوفة أصفار"""
        if isinstance(shape, int):
            return [0.0] * shape
        elif isinstance(shape, tuple):
            if len(shape) == 1:
                return [0.0] * shape[0]
            elif len(shape) == 2:
                return [[0.0] * shape[1] for _ in range(shape[0])]
    
    @staticmethod
    def ones(shape):
        """مصفوفة آحاد"""
        if isinstance(shape, int):
            return [1.0] * shape
        elif isinstance(shape, tuple):
            if len(shape) == 1:
                return [1.0] * shape[0]
            elif len(shape) == 2:
                return [[1.0] * shape[1] for _ in range(shape[0])]
    
    @staticmethod
    def arange(start, stop=None, step=1):
        """محاكاة np.arange"""
        if stop is None:
            stop = start
            start = 0
        result = []
        current = start
        while current < stop:
            result.append(current)
            current += step
        return result
    
    @staticmethod
    def linspace(start, stop, num=50):
        """محاكاة np.linspace"""
        if num <= 1:
            return [start]
        step = (stop - start) / (num - 1)
        return [start + i * step for i in range(num)]
    
    @staticmethod
    def exp(x):
        """دالة الأس"""
        if isinstance(x, (list, tuple)):
            return [math.exp(val) for val in x]
        return math.exp(x)
    
    @staticmethod
    def log(x):
        """دالة اللوغاريتم الطبيعي"""
        if isinstance(x, (list, tuple)):
            return [math.log(val) for val in x]
        return math.log(x)
    
    @staticmethod
    def sqrt(x):
        """الجذر التربيعي"""
        if isinstance(x, (list, tuple)):
            return [math.sqrt(val) for val in x]
        return math.sqrt(x)
    
    @staticmethod
    def sum(data, axis=None):
        """مجموع العناصر"""
        if isinstance(data[0], (list, tuple)) and axis is not None:
            # معالجة مصفوفات ثنائية (مبسطة)
            if axis == 0:
                # مجموع الأعمدة
                return [sum(col) for col in zip(*data)]
            elif axis == 1:
                # مجموع الصفوف
                return [sum(row) for row in data]
        # مجموع الكل
        if isinstance(data[0], (list, tuple)):
            return sum(sum(row) for row in data)
        return sum(data)
    
    @staticmethod
    def shape(arr):
        """الحصول على شكل المصفوفة"""
        if isinstance(arr, (list, tuple)):
            if arr and isinstance(arr[0], (list, tuple)):
                return (len(arr), len(arr[0]))
            return (len(arr),)
        return ()
    
    @staticmethod
    def reshape(arr, new_shape):
        """إعادة تشكيل المصفوفة (مبسطة)"""
        flat = []
        if isinstance(arr[0], (list, tuple)):
            for row in arr:
                flat.extend(row)
        else:
            flat = list(arr)
        
        if isinstance(new_shape, int):
            return flat[:new_shape]
        elif isinstance(new_shape, tuple):
            if len(new_shape) == 2:
                result = []
                idx = 0
                for i in range(new_shape[0]):
                    row = []
                    for j in range(new_shape[1]):
                        if idx < len(flat):
                            row.append(flat[idx])
                        else:
                            row.append(0.0)
                        idx += 1
                    result.append(row)
                return result
        return arr

# استبدال الوحدات المفقودة
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = FakeNumpy()
    HAS_NUMPY = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    class FakePsutil:
        """محاكاة psutil الأساسية"""
        @staticmethod
        def cpu_percent(interval=None, percpu=False):
            if interval:
                time.sleep(interval)
            if percpu:
                # إرجاع قائمة لكل نواة
                import multiprocessing
                cpu_count = multiprocessing.cpu_count()
                return [random.uniform(0, 100) for _ in range(cpu_count)]
            return random.uniform(0, 100)
        
        @staticmethod
        def virtual_memory():
            class Memory:
                def __init__(self):
                    self.percent = random.uniform(50, 90)
                    self.total = 16 * 1024 ** 3  # 16 GB
                    self.available = self.total * (100 - self.percent) / 100
                    self.used = self.total - self.available
                    self.free = self.available
            return Memory()
        
        @staticmethod
        def disk_usage(path):
            class Disk:
                def __init__(self):
                    self.percent = random.uniform(30, 90)
                    self.total = 500 * 1024 ** 3  # 500 GB
                    self.used = self.total * self.percent / 100
                    self.free = self.total - self.used
            return Disk()
        
        @staticmethod
        def cpu_count(logical=True):
            import multiprocessing
            return multiprocessing.cpu_count()
        
        @staticmethod
        def boot_time():
            return time.time() - random.uniform(3600, 86400*30)  # بين ساعة وشهر
        
        @staticmethod
        def Process(pid=None):
            class FakeProcess:
                def __init__(self, pid=None):
                    self.pid = pid or os.getpid()
                    self._name = "python.exe" if sys.platform == "win32" else "python"
                    self._status = "running"
                    self.memory_info = self.MemoryInfo()
                    self.cpu_percent_result = random.uniform(0, 100)
                
                class MemoryInfo:
                    def __init__(self):
                        self.rss = random.randint(10000000, 500000000)  # 10MB - 500MB
                        self.vms = random.randint(20000000, 1000000000)  # 20MB - 1GB
                
                def name(self):
                    return self._name
                
                def status(self):
                    return self._status
                
                def memory_percent(self):
                    return random.uniform(0.1, 5.0)
                
                def cpu_percent(self, interval=None):
                    if interval:
                        time.sleep(interval)
                    return self.cpu_percent_result
                
                def memory_info(self):
                    return self.memory_info
            
            return FakeProcess(pid)
        
        @staticmethod
        def process_iter():
            processes = []
            for i in range(random.randint(50, 200)):
                proc = FakePsutil.Process(pid=1000 + i)
                processes.append(proc)
            return processes
    
    psutil = FakePsutil()
    HAS_PSUTIL = False

# اختبار تشغيلي
if __name__ == "__main__":
    print(f"numpy متاحة: {HAS_NUMPY}")
    print(f"psutil متاحة: {HAS_PSUTIL}")
    
    print("\n" + "="*50)
    print("اختبار FakeNumpy:")
    print("="*50)
    
    print("1. np.random.rand():", np.random.rand())
    print("2. np.random.rand(5):", np.random.rand(5))
    print("3. np.random.rand(2, 3):", np.random.rand(2, 3))
    print("4. np.random.randn(5):", np.random.randn(5))
    
    print("\n5. np.dot([1, 2, 3], [4, 5, 6]):", np.dot([1, 2, 3], [4, 5, 6]))
    print("6. np.mean([1, 2, 3, 4, 5]):", np.mean([1, 2, 3, 4, 5]))
    print("7. np.std([1, 2, 3, 4, 5]):", np.std([1, 2, 3, 4, 5]))
    
    print("\n8. np.zeros(5):", np.zeros(5))
    print("9. np.ones((2, 3)):", np.ones((2, 3)))
    print("10. np.arange(5):", np.arange(5))
    print("11. np.linspace(0, 1, 5):", np.linspace(0, 1, 5))
    
    print("\n12. np.exp([0, 1, 2]):", np.exp([0, 1, 2]))
    print("13. np.log([1, 2.71828, 7.389]):", np.log([1, 2.71828, 7.389]))
    print("14. np.sqrt([4, 9, 16]):", np.sqrt([4, 9, 16]))
    
    matrix = [[1, 2], [3, 4], [5, 6]]
    print("\n15. شكل المصفوفة [[1,2],[3,4],[5,6]]:", np.shape(matrix))
    print("16. مجموع المصفوفة:", np.sum(matrix))
    print("17. مجموع الصفوف:", np.sum(matrix, axis=1))
    print("18. مجموع الأعمدة:", np.sum(matrix, axis=0))
    
    print("\n" + "="*50)
    print("اختبار FakePsutil:")
    print("="*50)
    
    print(f"1. عدد أنوية CPU: {psutil.cpu_count()}")
    print(f"2. استخدام CPU: {psutil.cpu_percent()}%")
    print(f"3. استخدام CPU لكل نواة: {psutil.cpu_percent(percpu=True)}")
    
    mem = psutil.virtual_memory()
    print(f"\n4. ذاكرة النظام:")
    print(f"   - النسبة: {mem.percent:.1f}%")
    print(f"   - الإجمالي: {mem.total / 1024**3:.1f} GB")
    print(f"   - المستخدم: {mem.used / 1024**3:.1f} GB")
    print(f"   - المتاح: {mem.available / 1024**3:.1f} GB")
    
    disk = psutil.disk_usage('/')
    print(f"\n5. استخدام القرص:")
    print(f"   - النسبة: {disk.percent:.1f}%")
    print(f"   - الإجمالي: {disk.total / 1024**3:.1f} GB")
    print(f"   - المستخدم: {disk.used / 1024**3:.1f} GB")
    print(f"   - المتاح: {disk.free / 1024**3:.1f} GB")
    
    print(f"\n6. وقت الإقلاع: {time.ctime(psutil.boot_time())}")
    
    print(f"\n7. عمليات النظام:")
    processes = list(psutil.process_iter())
    print(f"   - عدد العمليات: {len(processes)}")
    
    if processes:
        proc = processes[0]
        print(f"   - أول عملية (PID: {proc.pid}): {proc.name()}")
        print(f"   - حالة العملية: {proc.status()}")
        print(f"   - استخدام الذاكرة: {proc.memory_percent():.2f}%")
        print(f"   - استخدام CPU: {proc.cpu_percent():.1f}%")
