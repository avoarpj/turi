from abc import ABC, abstractmethod

class DynamicURL(ABC):
    @abstractmethod
    def gen_urls(self) -> list[str]:
        """
            Dynamic URL generation should be implemented on the child class
        """

        raise NotImplementedError