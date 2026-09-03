def check_if_realtor(raw_html, clean_text, title=""):
    text_lower = (title + " " + clean_text + " " + raw_html).lower()
    
    # Спершу вирізаємо фрази-протигази (де власники просять не турбувати)
    anti_realtor_phrases = [
        "рієлторам не турбувати", "ріелторам не турбувати", 
        "без рієлторів", "без ріелторів", "без агентств", 
        "агентствам не турбувати", "посередникам не турбувати"
    ]
    for phrase in anti_realtor_phrases:
        text_lower = text_lower.replace(phrase, "")

    # А далі вже шукаємо справжніх рієлторів
    if re.search(r'^\s*\d{4,6}\b', title) or re.search(r'\b(код|id)\s*[:#]?\s*\d{4,6}\b', text_lower):
        return True

    realtor_words = [
        "агентство", "комісія", "ріелтор", "рієлтор", "послуги агента", 
        "агенція", "маклер", "посередник", "представник агенції",
        "основа", "osnova", "оператор нерухомості"
    ]
    for word in realtor_words:
        if word in text_lower:
            return True

    if '"usertype":"business"' in text_lower or 'user_type_business' in text_lower or '"isbusiness":true' in text_lower:
        return True

    if 'приватна особа' in text_lower or '"usertype":"private"' in text_lower or 'user_type_private' in text_lower:
        return False

    return False
