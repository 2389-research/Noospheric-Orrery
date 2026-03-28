def build_classification_excerpt(title: str, content: str, max_window: int = 2000) -> str:
    header = f"Title: {title}\n\n"
    if len(content) <= 6000:
        return header + content
    begin = content[:max_window]
    mid_start = (len(content) - max_window) // 2
    middle = content[mid_start:mid_start + max_window]
    end = content[-max_window:]
    return (header + "--- Beginning ---\n" + begin + "\n\n" + "--- Middle ---\n" + middle + "\n\n" + "--- End ---\n" + end)
