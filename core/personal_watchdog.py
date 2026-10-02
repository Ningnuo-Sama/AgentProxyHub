"""个人控制器失联保护：只调用个人停止，不启动或干预业务内核。"""


class PersonalControllerGuard:
    def __init__(self, stop_personal, threshold=3):
        if threshold < 3:
            raise ValueError('at_least_three_samples_required')
        self.stop_personal = stop_personal
        self.threshold = threshold
        self.failures = 0
        self.latched = False

    def observe(self, state, *, manual_halt=False):
        if manual_halt:
            return {'action': 'respect_manual_halt'}
        if state.get('ok') is True:
            self.failures = 0
            return {'action': 'controller_healthy'}
        self.failures += 1
        if self.failures < self.threshold or self.latched:
            return {'action': 'controller_unknown', 'failures': self.failures, 'latched': self.latched}
        self.latched = True
        result = self.stop_personal()
        return {'action': 'stop_personal_on_controller_loss', 'result': result,
                'business_kernel_changed': False}
