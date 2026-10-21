"""Turkish tax number (VKN) checksum. Lets extraction tell a misread VKN from a real one."""


def check_digit(first_nine: str) -> int:
    total = 0
    for i, ch in enumerate(first_nine):
        tmp = (int(ch) + 9 - i) % 10
        total += 9 if tmp == 9 else (tmp * 2 ** (9 - i)) % 9
    return (10 - total % 10) % 10


def is_valid(vkn: str) -> bool:
    return len(vkn) == 10 and vkn.isdigit() and check_digit(vkn[:9]) == int(vkn[9])
