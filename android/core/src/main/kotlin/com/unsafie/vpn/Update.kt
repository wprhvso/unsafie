package com.unsafie.vpn

val UPDATE_ABIS = listOf("arm64-v8a", "armeabi-v7a")

fun updatesConfigured(baseUrl: String, token: String): Boolean = baseUrl.isNotEmpty() && token.isNotEmpty()

fun updateAbi(supported: List<String>): String? = supported.firstOrNull { it in UPDATE_ABIS }

fun updateApkUrl(baseUrl: String, version: String, abi: String): String = "${baseUrl.trimEnd('/')}/$version/$abi"

fun isNewerVersion(current: String, candidate: String): Boolean = compareVersions(candidate, current) > 0

fun compareVersions(left: String, right: String): Int {
    val a = releaseNumbers(left)
    val b = releaseNumbers(right)
    for (i in 0 until maxOf(a.size, b.size)) {
        val order = a.getOrElse(i) { 0 }.compareTo(b.getOrElse(i) { 0 })
        if (order != 0) return order
    }
    return releaseRank(left).compareTo(releaseRank(right))
}

private fun releaseNumbers(version: String): List<Int> =
    version
        .trim()
        .removePrefix("v")
        .substringBefore('-')
        .split('.')
        .map { it.toIntOrNull() ?: 0 }

private fun releaseRank(version: String): Int = if (version.contains('-')) 0 else 1
