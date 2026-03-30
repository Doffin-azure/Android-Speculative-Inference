plugins {
    alias(libs.plugins.android.library)
}

val localProperties = java.util.Properties().apply {
    val localFile = rootProject.file("gradle-local.properties")
    if (localFile.exists()) {
        localFile.inputStream().use(::load)
    }
}

val llamaCppSourceDir = providers.gradleProperty("llamaCppSourceDir").orNull
    ?: localProperties.getProperty("llamaCppSourceDir")
    ?: System.getenv("LLAMA_CPP_SRC")

android {
    namespace = "com.example.myapplication.llama"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        minSdk = 26

        consumerProguardFiles("consumer-rules.pro")

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                cppFlags += ""
                if (!llamaCppSourceDir.isNullOrBlank()) {
                    arguments += "-DLLAMA_CPP_SRC=$llamaCppSourceDir"
                }
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
}
