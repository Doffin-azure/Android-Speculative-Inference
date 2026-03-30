import java.util.Properties

plugins {
    alias(libs.plugins.android.library)
}

// Machine-local configuration only. Do not commit llama.cpp checkout paths.
val localProperties = Properties().apply {
    val localFile = rootProject.file("gradle-local.properties")
    if (localFile.exists()) {
        localFile.inputStream().use { input ->
            load(input)
        }
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
                arguments += "-DCMAKE_BUILD_TYPE=Release"
                arguments += "-DBUILD_SHARED_LIBS=ON"
                arguments += "-DLLAMA_BUILD_COMMON=ON"
                arguments += "-DLLAMA_OPENSSL=OFF"
                arguments += "-DGGML_NATIVE=OFF"
                arguments += "-DGGML_BACKEND_DL=ON"
                arguments += "-DGGML_CPU_ALL_VARIANTS=ON"
                arguments += "-DGGML_LLAMAFILE=OFF"
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
