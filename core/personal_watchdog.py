"""个人控制器失联保护：只关闭个人意图，不启动或干预业务内核。"""


def close_personal_safely():
    from .personal_route_state import close_personal
    return close_personal()


class PersonalControllerGuard:
    def __init__(self, stop_personal, threshold=3):
        if threshold < 3:
            raise ValueError('at_least_three_samples_required')
        self.stop_personal = stop_personal
        self.close_personal = close_personal_safely
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
        result = self.close_personal()
        return {'action': 'stop_personal_on_controller_loss', 'result': result,
                'business_kernel_changed': False}
