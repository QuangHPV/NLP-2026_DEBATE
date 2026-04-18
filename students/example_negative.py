from debate_eval.api import BaseAgent


class Agent(BaseAgent):
    def argue(self, chat_history):
        return self.chat(
            history=chat_history,
            user_prompt=(
                f"请作为反方继续辩论。辩题：{self.topic}\n"
                f"材料：{self.material}\n"
                "请结合材料和对手最新观点，输出一句克制但有力的中文反驳。"
            ),
        )
